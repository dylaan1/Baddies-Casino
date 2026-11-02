"""The casino floor's DATA windows: choosing a game, then its Historical
Session Data (a table of sessions, newest first, each with a detail view) or
its P/L Chart (the running P/L, round by round, as a line). The figures come
from each game (casino/records.py); the marquee keeps moving behind every
window.

Each window is a function taking the curses window and the floor
(casino/floor.py): `floor.marquee` keeps the lights going, and
`backdrop()` redraws the floor itself behind the small windows."""
from __future__ import annotations

import curses
from datetime import datetime
from typing import Callable, List, Optional, Sequence, Tuple

from . import charts, tui
from .records import PLHistory, RecordsError, SessionRecord, money, signed

SESSION_COLUMNS = (  # heading, width, right-aligned
    ("Started", 16, False),
    ("Length", 8, True),
    ("Rounds", 6, True),
    ("Hands", 6, True),
    ("W-L-P", 12, True),
    ("Wagered", 13, True),
    ("Main P/L", 13, True),
    ("Side P/L", 12, True),
    ("Total P/L", 13, True),
    ("EV", 8, True),
)


def _when(stamp: Optional[str]) -> Optional[datetime]:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def local_time(stamp: Optional[str]) -> str:
    when = _when(stamp)
    return when.strftime("%Y-%m-%d %H:%M") if when else (stamp or "")


def session_length(record: SessionRecord) -> str:
    start, end = _when(record.started_at), _when(record.ended_at)
    if start is None:
        return ""
    if end is None:
        return "playing"
    minutes = max(0, round((end - start).total_seconds() / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60}h {minutes % 60:02d}m"


def percent(ev: Optional[float]) -> str:
    return "-" if ev is None else f"{ev:+.1f}%"


def _row(cells: Sequence[str]) -> str:
    return "  ".join(c.rjust(w) if right else c.ljust(w) for c, (_, w, right) in zip(cells, SESSION_COLUMNS))


def session_header() -> str:
    return _row([heading for heading, _, _ in SESSION_COLUMNS])


def session_row(r: SessionRecord) -> str:
    return _row([
        local_time(r.started_at),
        session_length(r),
        f"{r.rounds:,}",
        f"{r.hands:,}",
        f"{r.won}-{r.lost}-{r.pushed}",
        money(r.wagered),
        signed(r.main_pl),
        signed(r.side_pl),
        signed(r.total_pl),
        percent(r.ev),
    ])


def session_totals(records: List[SessionRecord]) -> str:
    wagered = sum(r.wagered for r in records)
    main = sum(r.main_pl for r in records)
    total = sum(r.total_pl for r in records)
    ev = percent(main / wagered * 100 if wagered > 0 else None)
    return (
        f"{len(records):,} session{'s' if len(records) != 1 else ''}  ·  {sum(r.hands for r in records):,} hands  ·  "
        f"{sum(r.rounds for r in records):,} rounds  ·  wagered {money(wagered)}  ·  Total P/L {signed(total)}  ·  EV {ev}"
    )


def session_detail(r: SessionRecord) -> List[Tuple[str, str]]:
    end = local_time(r.ended_at) if r.ended_at else "still playing"
    return [
        ("Started", local_time(r.started_at)),
        ("Ended", f"{end}  ({session_length(r)})" if r.ended_at else end),
        ("Rounds", f"{r.rounds:,}"),
        ("Hands", f"{r.hands:,}"),
        ("Won / lost / pushed", f"{r.won} / {r.lost} / {r.pushed}"),
        ("Wagered (main bets)", money(r.wagered)),
        ("Main P/L", signed(r.main_pl)),
        ("Side-bet P/L", signed(r.side_pl)),
        ("Total P/L", signed(r.total_pl)),
        ("EV (main bets)", percent(r.ev)),
        ("", ""),
    ] + list(r.details)


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


def pick_game(win, floor, title: str, backdrop: Callable[[], None]):
    """A small list of every game on the floor; returns the one picked, or
    None (Esc, q, or a click outside the list)."""
    games = floor.games
    view = tui.Viewport(len(games), 1)
    while True:
        backdrop()
        height, _ = win.getmaxyx()
        rows = max(1, min(len(games), height - 12))
        view.resize(rows)
        width = max(44, len(title) + 8, max((len(g.name) for g in games), default=0) + 10)
        y, x, inner = tui.modal_frame(win, title, rows + 2, width)
        tui.put(win, y + 2, x + 2, "Choose a game:", curses.A_DIM)
        for row, index in enumerate(view.visible):
            lit = index == view.cursor
            label = f" {'▶' if lit else ' '} {games[index].name}"
            tui.put(win, y + 3 + row, x + 2, label.ljust(inner), curses.A_REVERSE if lit else 0)
        more = ("▲ " if view.more_above else "  ") + ("▼" if view.more_below else " ")
        tui.put(win, y + 4 + rows, x + 2, f"{more} Enter select   Esc back", curses.A_DIM)
        floor.marquee.draw(win)
        win.refresh()
        ch = tui.getch(win, floor.marquee)
        if view.key(ch):
            continue
        if ch in tui.ENTER_KEYS and games:
            return games[view.cursor]
        if ch in tui.BACK_KEYS:
            return None
        if ch == curses.KEY_MOUSE:
            event = tui.mouse()
            if event is None:
                continue
            my, mx, bstate = event
            if tui.wheel(bstate):
                view.move(tui.wheel(bstate))
            elif tui.clicked(bstate):
                index = view.top + (my - (y + 3))
                inside = x <= mx < x + inner + 4 and y <= my < y + rows + 6
                if not inside:
                    return None
                if y + 3 <= my < y + 3 + rows and index < len(games):
                    if index == view.cursor:
                        return games[index]
                    view.move(index - view.cursor)


def _message_window(win, floor, title: str, lines: List[str], backdrop: Callable[[], None]) -> None:
    def redraw() -> None:
        backdrop()
        y, x, _ = tui.modal_frame(win, title, len(lines) + 2, max(50, max(map(len, lines), default=0) + 6))
        for i, line in enumerate(lines):
            tui.put(win, y + 2 + i, x + 2, line)
        tui.put(win, y + 3 + len(lines), x + 2, "Press any key to return", curses.A_DIM)
        floor.marquee.draw(win)
        win.refresh()

    redraw()
    tui.wait_key(win, floor.marquee, redraw)


def _full_window(win, floor, title: str) -> Tuple[int, int, int, int]:
    """Clear the screen down to the marquee and frame a full window; returns
    its inside (y, x, height, width)."""
    win.erase()
    y, x, h, w = tui.window_rect(win)
    tui.box(win, y, x, h, w, title, tui.color(tui.FOCUS) | curses.A_BOLD)
    return y + 1, x + 2, h - 2, w - 4


def show_sessions(win, floor, game, backdrop: Callable[[], None]) -> None:
    title = f"{game.name.upper()} — HISTORICAL SESSION DATA"
    try:
        records = game.sessions() if game.sessions else []
    except RecordsError as exc:
        _message_window(win, floor, title, [str(exc)], backdrop)
        return
    if not records:
        _message_window(win, floor, title, [f"No {game.name} sessions recorded yet."], backdrop)
        return
    lines = [session_row(r) for r in records]
    view = tui.Viewport(len(lines), 1)
    while True:
        y, x, h, w = _full_window(win, floor, title)
        rows = max(1, h - 6)
        view.resize(rows)
        tui.put(win, y + 1, x, session_totals(records)[:w], curses.A_BOLD)
        tui.put(win, y + 3, x, ("  " + session_header())[:w], curses.A_BOLD | curses.A_UNDERLINE)
        for row, index in enumerate(view.visible):
            lit = index == view.cursor
            text = f"{'▶' if lit else ' '} {lines[index]}"
            tui.put(win, y + 4 + row, x, text[:w].ljust(w) if lit else text[:w], curses.A_REVERSE if lit else 0)
        more = ("▲ " if view.more_above else "  ") + ("▼" if view.more_below else " ")
        tui.put(win, y + h - 1, x, f"{more} ↑↓ PgUp/PgDn scroll   Enter session detail   Esc back", curses.A_DIM)
        floor.marquee.draw(win)
        win.refresh()
        ch = tui.getch(win, floor.marquee)
        if view.key(ch):
            continue
        if ch in tui.BACK_KEYS:
            return
        if ch in tui.ENTER_KEYS:
            show_session_detail(win, floor, game, records[view.cursor])
        elif ch == curses.KEY_MOUSE:
            event = tui.mouse()
            if event is None:
                continue
            my, _, bstate = event
            if tui.wheel(bstate):
                view.move(tui.wheel(bstate))
            elif tui.clicked(bstate) and y + 4 <= my < y + 4 + rows:
                index = view.top + (my - (y + 4))
                if index == view.cursor:
                    show_session_detail(win, floor, game, records[index])
                elif index < len(lines):
                    view.move(index - view.cursor)


def show_session_detail(win, floor, game, record: SessionRecord) -> None:
    """One session's every figure, in a box over the table (it scrolls if
    the window's too short for all of them)."""
    rows = session_detail(record)
    title = f"{game.name.upper()} — SESSION #{record.number}"
    label_w = max(len(label) for label, _ in rows) + 4
    top = 0
    while True:
        height, _ = win.getmaxyx()
        shown = max(1, min(len(rows), height - 12))
        top = max(0, min(top, len(rows) - shown))
        y, x, inner = tui.modal_frame(win, title, shown + 2, 64)
        for i, (label, value) in enumerate(rows[top : top + shown]):
            tui.put(win, y + 2 + i, x + 2, f"{label:<{label_w}}{value}"[:inner], curses.A_BOLD if label == "Total P/L" else 0)
        more = ("▲ " if top > 0 else "  ") + ("▼" if top + shown < len(rows) else " ")
        tui.put(win, y + 3 + shown, x + 2, f"{more} Esc, q or Enter to return", curses.A_DIM)
        floor.marquee.draw(win)
        win.refresh()
        ch = tui.getch(win, floor.marquee)
        scroll = {curses.KEY_UP: -1, curses.KEY_DOWN: 1, curses.KEY_PPAGE: -shown, curses.KEY_NPAGE: shown,
                  curses.KEY_HOME: -len(rows), curses.KEY_END: len(rows)}
        if ch in scroll:
            top += scroll[ch]
        elif ch == curses.KEY_RESIZE:
            continue
        elif ch == curses.KEY_MOUSE:
            event = tui.mouse()
            if event is not None and tui.clicked(event[2]):
                return
        elif ch in tui.BACK_KEYS + tui.ENTER_KEYS:
            return


def show_chart(win, floor, game, backdrop: Callable[[], None]) -> None:
    title = f"{game.name.upper()} — LIFETIME P/L"
    try:
        history = game.pl_history() if game.pl_history else PLHistory()
    except RecordsError as exc:
        _message_window(win, floor, title, [str(exc)], backdrop)
        return
    if not history.rounds:
        _message_window(win, floor, title, [f"No {game.name} rounds recorded yet."], backdrop)
        return
    values = [0.0] + [pl for _, pl in history.rounds]
    while True:
        draw_chart(win, floor, title, history, values)
        ch = tui.getch(win, floor.marquee)
        if ch == curses.KEY_RESIZE:
            continue
        if ch in tui.BACK_KEYS + tui.ENTER_KEYS:
            return
        if ch == curses.KEY_MOUSE:
            event = tui.mouse()
            if event is not None and tui.clicked(event[2]):
                return


def _day(when: Optional[datetime], year: bool = False) -> str:
    if when is None:
        return ""
    return f"{when:%b} {when.day}, {when.year}" if year else f"{when:%b} {when.day}"


def chart_summary(history: PLHistory) -> str:
    pls = [pl for _, pl in history.rounds]
    first, last = _when(history.rounds[0][0]), _when(history.rounds[-1][0])
    span = f"{_day(first, True)} – {_day(last, True)}"
    return (
        f"{len(pls):,} rounds  ·  {span}  ·  now {signed(pls[-1])}  ·  high {signed(max(max(pls), 0.0))}  ·  "
        f"low {signed(min(min(pls), 0.0))}"
    )


def draw_chart(win, floor, title: str, history: PLHistory, values: List[float]) -> None:
    y, x, h, w = _full_window(win, floor, title)
    tui.put(win, y + 1, x, chart_summary(history)[:w], curses.A_BOLD)
    note_rows = 2 if abs(history.unrecorded) > 1e-9 else 0
    plot_rows = max(3, h - 8 - note_rows)
    label_w = 12
    plot_x = x + label_w + 1
    cols = max(10, w - label_w - 3)
    chart = charts.line_chart(values, plot_rows, cols)
    labels = {row: charts.money_label(v) for row, v in chart.ticks}
    top = y + 3
    line_attr = tui.color(tui.SIGN) | curses.A_BOLD
    for r in range(plot_rows):
        if r in labels:
            tui.put(win, top + r, x, labels[r].rjust(label_w - 1))
        tui.put(win, top + r, plot_x - 1, "┤" if r in labels else "│", curses.A_DIM)
        row = chart.cells[r]
        c = 0
        while c < cols:  # runs of line dots, zero line, or nothing, each drawn in one go
            blank = row[c] == charts.BLANK
            end = c
            while end < cols and (row[end] == charts.BLANK) == blank:
                end += 1
            if not blank:
                tui.put(win, top + r, plot_x + c, row[c:end], line_attr)
            elif r == chart.zero_row:
                tui.put(win, top + r, plot_x + c, "┈" * (end - c), curses.A_DIM)
            c = end
    # the round axis: ticks at the start, quarters, and end, with round numbers and dates
    axis_y = top + plot_rows
    n = len(history.rounds)
    marks = sorted({round(f * (cols - 1)) for f in (0, 0.25, 0.5, 0.75, 1)})
    axis = ["─"] * cols
    for m in marks:
        axis[m] = "┬"
    tui.put(win, axis_y, plot_x - 1, "└" + "".join(axis), curses.A_DIM)
    for m in marks:
        index = max(0, min(n - 1, round(m / max(cols - 1, 1) * (n - 1))))
        when = _when(history.rounds[index][0])
        for dy, text in ((1, f"round {index + 1:,}"), (2, _day(when))):
            tx = plot_x + m - (len(text) if m == cols - 1 else (len(text) // 2 if m else 0))
            tui.put(win, axis_y + dy, max(plot_x, tx), text, curses.A_DIM)
    if note_rows:
        tui.put(
            win,
            axis_y + 4,
            x,
            f"Not charted: {signed(history.unrecorded)} of older play with no round-by-round record "
            f"(it's in the game's Lifetime P/L).",
            curses.A_DIM,
        )
    tui.put(win, y + h - 1, x, "Esc, q or Enter to return", curses.A_DIM)
    floor.marquee.draw(win)
    win.refresh()
