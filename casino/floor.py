"""The casino floor: Baddie's Casino's title screen, and where every game
starts.

    python3 -m casino

The BADDIE'S CASINO sign runs across the top in big lime-green block
letters, over a purple "Luxury Gaming and Amenities" banner, and under them
sit two menus side by side: GAMES, to sit down at a game, and BANK, for the
casino bank everything plays from (casino/bank.py) -- its summary and
transaction list, and deposits and withdrawals. The bottom 15% of the screen
holds no tables: just the balance, any message, the keys, and on the last
line the intellectual-property notice.

Up/Down move through a menu and stop at its first and last option, so the
highlight never falls off the end; a menu longer than its box scrolls to keep
the highlight in view. Left/Right or Tab switch menus, Enter picks the
highlighted option (so does clicking it once it's highlighted), and q leaves
the casino. Clicking anywhere off the menus clears the highlight; an arrow key
or a click on an option brings it back.

A game runs exactly as it does on its own (python3 -m blackjack): the floor
steps out of curses, the game takes over the terminal, and quitting the game
comes back to the floor.
"""
from __future__ import annotations

import curses
import math
import signal
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from .bank import Bank, Opening

# --------------------------------------------------------------------------
# The sign
# --------------------------------------------------------------------------

# Five rows per letter; "#" is a filled cell, drawn as a full block.
_FONT: Dict[str, Tuple[str, ...]] = {
    "B": ("####.", "#...#", "####.", "#...#", "####."),
    "A": (".###.", "#...#", "#####", "#...#", "#...#"),
    "D": ("####.", "#...#", "#...#", "#...#", "####."),
    "I": ("###", ".#.", ".#.", ".#.", "###"),
    "E": ("#####", "#....", "####.", "#....", "#####"),
    "'": ("#", "#", ".", ".", "."),
    "S": (".####", "#....", ".###.", "....#", "####."),
    "C": (".####", "#....", "#....", "#....", ".####"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", ".###."),
    " ": ("...", "...", "...", "...", "..."),
}
SIGN_TEXT = "BADDIE'S CASINO"
BLOCK = "█"


# The sizes the sign comes in, biggest first, as (columns, rows) per font
# cell. A terminal cell is about twice as tall as it is wide, so a cell twice
# as many columns as rows keeps the letters' proportions: (4, 2) is double the
# (2, 1) size, and (1, 1) is the compact fallback.
SIGN_SCALES = ((4, 2), (2, 1), (1, 1))


def sign_rows(text: str, cell_w: int, cell_h: int = 1) -> List[str]:
    """`text` in block letters, each font cell `cell_w` columns wide and
    `cell_h` rows tall, with one blank cell between letters."""
    gap = " " * cell_w
    rows = [
        gap.join("".join(BLOCK * cell_w if px == "#" else " " * cell_w for px in _FONT[ch][row]) for ch in text)
        for row in range(5)
    ]
    return [row for row in rows for _ in range(cell_h)]


def fit_sign(width: int, height: int) -> List[str]:
    """The biggest version of the sign that fits in `width` x `height`: each
    size on one line, then stacked as BADDIE'S over CASINO -- or, in a tiny
    window, the name in plain text."""
    first, second = SIGN_TEXT.split(" ")
    for cell_w, cell_h in SIGN_SCALES:
        one_line = sign_rows(SIGN_TEXT, cell_w, cell_h)
        stacked = sign_rows(first, cell_w, cell_h) + [""] * cell_h + sign_rows(second, cell_w, cell_h)
        for rows in (one_line, stacked):
            if max(len(r) for r in rows) <= width - 4 and len(rows) <= height:
                return rows
    return [SIGN_TEXT]


# --------------------------------------------------------------------------
# Menus
# --------------------------------------------------------------------------


class Viewport:
    """A cursor over `count` rows, `rows` of them visible at once. The cursor
    stops at the first and last row (it never runs off either end), and the
    view scrolls just enough to keep it visible."""

    def __init__(self, count: int, rows: int):
        self.count = count
        self.rows = max(1, rows)
        self.cursor = 0
        self.top = 0

    def move(self, delta: int) -> None:
        self.cursor = max(0, min(self.count - 1, self.cursor + delta)) if self.count else 0
        self._follow()

    def page(self, direction: int) -> None:
        self.move(direction * self.rows)

    def home(self) -> None:
        self.move(-self.count)

    def end(self) -> None:
        self.move(self.count)

    def resize(self, rows: int) -> None:
        self.rows = max(1, rows)
        self._follow()

    def _follow(self) -> None:
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + self.rows:
            self.top = self.cursor - self.rows + 1
        self.top = max(0, min(self.top, max(0, self.count - self.rows)))

    @property
    def visible(self) -> range:
        return range(self.top, min(self.count, self.top + self.rows))

    @property
    def more_above(self) -> bool:
        return self.top > 0

    @property
    def more_below(self) -> bool:
        return self.top + self.rows < self.count


@dataclass(frozen=True)
class MenuItem:
    label: str
    action: str  # what picking it does -- see Floor.perform


class Menu:
    def __init__(self, title: str, items: List[MenuItem], rows: int):
        self.title = title
        self.items = items
        self.view = Viewport(len(items), rows)

    @property
    def cursor(self) -> int:
        return self.view.cursor

    @property
    def current(self) -> MenuItem:
        return self.items[self.view.cursor]


@dataclass(frozen=True)
class Game:
    name: str
    bank_key: str  # the game's entry in the bank's game_winnings
    launch: Callable[[], None]  # runs the game to completion in the terminal, as its own `python3 -m` would


def _play_blackjack() -> None:
    from blackjack.ui import run

    run()


def _blackjack_opening() -> Opening:
    # Blackjack kept the bankroll itself before the bank existed: the first
    # time the bank is opened, from here or from the game, it starts from that.
    from blackjack.bank import opening

    return opening()


# Every game on the floor, in menu order -- a new game is one more entry.
GAMES: List[Game] = [Game("Classic Blackjack", "blackjack", _play_blackjack)]
BANK_ITEMS = [
    MenuItem("Account Summary", "summary"),
    MenuItem("Deposit", "deposit"),
    MenuItem("Withdraw", "withdraw"),
    MenuItem("Transactions", "transactions"),
]

# A terminal can't measure inches, so the floor's margins are set in columns
# per inch: about 21 for Monaco 10 pt on a 13-inch MacBook Pro at its default
# scaled resolution. A different font size or display scaling changes it.
COLUMNS_PER_INCH = 21
BANNER_MARGIN_IN = 3  # inches clear on either side of the banner
MENU_MARGIN_IN = 1  # inches between each menu and its side of the screen
MENU_GAP = 4  # columns between the two menus
MIN_MENU_W = 26
MIN_MENU_ROWS = 4  # options a menu shows before the sign is made smaller to fit them; past this, menus scroll
BOTTOM_CLEAR = 0.15  # the bottom 15% of the screen holds no tables
BANNER_TEXT = "Luxury Gaming and Amenities"
LEAVE_TEXT = "q  Leave Casino"
FOOTER = "↑↓ choose   ←→/Tab switch menu   Enter select   click away to clear   q leave"
NOTICE = (
    "Intellectual Property of Dylan Behseresht, 2026. Any unauthorized redistribution of this software without "
    "express written consent is expressly prohibited"
)


@dataclass
class Layout:
    """Where everything on the floor goes for one window size."""

    sign: List[str]
    sign_y: int
    banner_y: int
    banner_x: int
    banner_w: int
    boxes: List[Tuple[int, int]]  # each menu box's top-left (y, x)
    box_w: int
    box_h: int
    status_y: int  # balance (left) and LEAVE_TEXT (right), just under the boxes
    message_y: int
    leave_x: int
    footer_y: int  # the keys
    notice: List[str]  # NOTICE, as one line or (in a narrow window) wrapped, ending on the bottom line
    notice_y: int  # the row its first line is on
    fits: bool = True


class Floor:
    """The floor's state and what each key or click does to it, apart from
    drawing -- so it can be exercised without a terminal."""

    def __init__(self, games: Optional[List[Game]] = None, bank_opener: Optional[Callable[[], Bank]] = None):
        self.games = list(GAMES if games is None else games)
        self.menus = [
            Menu("GAMES", [MenuItem(g.name, f"game:{i}") for i, g in enumerate(self.games)], MIN_MENU_ROWS),
            Menu("BANK", list(BANK_ITEMS), MIN_MENU_ROWS),
        ]
        self.focus: Optional[int] = 0  # the menu holding the highlight, or None once it's been clicked off
        self.last_focus = 0
        self.message = ""
        self._bank_opener = bank_opener or (lambda: Bank.open(opening=_blackjack_opening))
        self.bank: Optional[Bank] = None
        self.layout_cache: Optional[Layout] = None

    def open_bank(self) -> None:
        """(Re)read the bank -- on arrival, and back from a game, which has
        been playing from it."""
        self.bank = self._bank_opener()
        if self.bank.warning:
            self.message = self.bank.warning
            self.bank.warning = None
        elif self.bank.error:
            self.message = f"The bank file couldn't be saved ({self.bank.error})"

    # ---- layout ----

    def layout(self, height: int, width: int) -> Layout:
        """Top to bottom: a blank row, the sign, a blank row, the banner, a
        blank row, then the menu boxes down to where the bottom 15% of the
        screen begins. That bottom stretch holds the status row (balance,
        Leave Casino), the message row, the keys, and the notice on the very
        last row. Across, each menu runs from MENU_MARGIN_IN inches in from its
        side of the screen to MENU_GAP columns from the other, and the banner
        keeps BANNER_MARGIN_IN inches clear on either side. In a smaller
        window the sign shrinks first, then the margins; menus with more
        options than they have room for scroll."""
        inch = COLUMNS_PER_INCH
        notice = textwrap.wrap(NOTICE, max(20, width - 2))
        bottom = max(3 + len(notice), math.ceil(height * BOTTOM_CLEAR))  # kept clear of tables: status, message, keys, notice
        box_last = height - bottom - 1  # the last row a box may use

        count = len(self.menus)
        margin = min(MENU_MARGIN_IN * inch, max(0, (width - (count - 1) * MENU_GAP - count * MIN_MENU_W) // 2))
        box_w = (width - 2 * margin - (count - 1) * MENU_GAP) // count
        xs = [margin + m * (box_w + MENU_GAP) for m in range(count - 1)] + [width - margin - box_w]

        banner_margin = min(BANNER_MARGIN_IN * inch, max(0, (width - len(BANNER_TEXT) - 6) // 2))

        sign_y = 1
        sign = fit_sign(width, (box_last + 1) - sign_y - 3 - (MIN_MENU_ROWS + 2))  # 3: blank, banner, blank
        banner_y = sign_y + len(sign) + 1
        box_y = banner_y + 2
        box_h = box_last - box_y + 1
        for m in self.menus:
            m.view.resize(box_h - 2)
        lay = Layout(
            sign=sign,
            sign_y=sign_y,
            banner_y=banner_y,
            banner_x=banner_margin,
            banner_w=width - 2 * banner_margin,
            boxes=[(box_y, x) for x in xs],
            box_w=box_w,
            box_h=box_h,
            status_y=box_last + 1,
            message_y=box_last + 2,
            leave_x=xs[-1] + box_w - len(LEAVE_TEXT) - 1,
            footer_y=height - len(notice) - 1,
            notice=notice,
            notice_y=height - len(notice),
            fits=box_w >= MIN_MENU_W and box_h >= 3,
        )
        self.layout_cache = lay
        return lay

    def item_at(self, y: int, x: int) -> Optional[Tuple[int, Optional[int]]]:
        """(menu, option) under a screen position -- option None on the box's
        border or title -- else None (off the menus)."""
        lay = self.layout_cache
        if lay is None:
            return None
        for m, (by, bx) in enumerate(lay.boxes):
            if by <= y < by + lay.box_h and bx <= x < bx + lay.box_w:
                row = y - by - 1
                view = self.menus[m].view
                if 0 <= row < view.rows and view.top + row < view.count and 0 < x - bx < lay.box_w - 1:
                    return m, view.top + row
                return m, None
        return None

    # ---- input ----

    def _refocus(self, menu: Optional[int] = None) -> None:
        self.focus = self.last_focus if menu is None else menu
        self.last_focus = self.focus

    def key(self, ch: int) -> Optional[str]:
        """Apply a key press; returns the action to perform, if any."""
        if ch in (ord("q"), ord("Q")):
            return "quit"
        if ch == 27:  # Esc: same as clicking off
            self.focus = None
            return None
        if ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
            step = -1 if ch == curses.KEY_LEFT else 1
            self._refocus(None if self.focus is None else max(0, min(len(self.menus) - 1, self.focus + step)))
            return None
        if ch in (9, curses.KEY_BTAB):  # Tab / Shift-Tab go round
            step = 1 if ch == 9 else -1
            self._refocus(None if self.focus is None else (self.focus + step) % len(self.menus))
            return None
        moves = {
            curses.KEY_UP: lambda v: v.move(-1),
            curses.KEY_DOWN: lambda v: v.move(1),
            curses.KEY_PPAGE: lambda v: v.page(-1),
            curses.KEY_NPAGE: lambda v: v.page(1),
            curses.KEY_HOME: lambda v: v.home(),
            curses.KEY_END: lambda v: v.end(),
        }
        if ch in moves:
            if self.focus is None:
                self._refocus()  # the first arrow after clicking off just brings the highlight back
            else:
                moves[ch](self.menus[self.focus].view)
            return None
        if ch in (10, 13, curses.KEY_ENTER, ord(" ")) and self.focus is not None:
            return self.menus[self.focus].current.action
        return None

    def click(self, y: int, x: int) -> Optional[str]:
        """A left click: highlight the option under it, or pick it if it's
        already highlighted; on a menu's border, move into that menu; off the
        menus, clear the highlight (or leave, on LEAVE_TEXT)."""
        lay = self.layout_cache
        if lay is not None and y == lay.status_y and lay.leave_x <= x < lay.leave_x + len(LEAVE_TEXT):
            return "quit"
        hit = self.item_at(y, x)
        if hit is None:
            self.focus = None
            return None
        menu, option = hit
        if option is None:
            self._refocus(menu)
            return None
        view = self.menus[menu].view
        if self.focus == menu and view.cursor == option:
            return self.menus[menu].current.action
        self._refocus(menu)
        view.move(option - view.cursor)
        return None

    def wheel(self, y: int, x: int, direction: int) -> None:
        """Scroll wheel over a menu: move its highlight a row."""
        hit = self.item_at(y, x)
        if hit is not None:
            self._refocus(hit[0])
            self.menus[hit[0]].view.move(direction)

    # ---- the bank's figures, as the floor shows them ----

    def summary_lines(self) -> List[Tuple[str, str]]:
        bank = self.bank
        rows = [("Balance", _money(bank.balance)), ("", "")]
        rows.append(("Won at the games", _signed(bank.total_winnings)))
        names = {g.bank_key: g.name for g in self.games}
        for key in list(names) + sorted(k for k in bank.game_winnings if k not in names):
            rows.append((f"  {names.get(key, key.title())}", _signed(bank.game_winnings.get(key, 0.0))))
        rows += [
            ("Deposited", _money(bank.deposited)),
            ("Withdrawn", _money(bank.withdrawn)),
            ("", ""),
            ("Balance = deposited - withdrawn + won", ""),
        ]
        return rows

    def transaction_lines(self) -> List[str]:
        """Deposits and withdrawals, newest first."""
        lines = []
        for t in reversed(self.bank.transactions):
            kind = {"opening": "Opening", "deposit": "Deposit", "withdrawal": "Withdrawal"}.get(t.get("kind"), str(t.get("kind")))
            lines.append(
                f"{_local_time(t.get('at', '')):<17}  {kind:<10}  {_signed(float(t.get('amount', 0))):>14}  "
                f"{_money(float(t.get('balance', 0))):>14}  {t.get('note', '')}"
            )
        return lines

    def move_money(self, action: str, amount: float) -> str:
        """A deposit or withdrawal from the floor; returns the message to show."""
        bank = self.bank
        if amount <= 0:
            return "Enter an amount above $0."
        if action == "withdraw" and amount > bank.balance + 1e-9:
            return f"You can withdraw at most {_money(max(bank.balance, 0.0))}."
        ok = bank.deposit(amount, "Casino floor") if action == "deposit" else bank.withdraw(amount, "Casino floor")
        verb = "Deposited" if action == "deposit" else "Withdrew"
        note = "" if ok else f" (but the bank file couldn't be saved: {bank.error})"
        return f"{verb} {_money(amount)} -- balance {_money(bank.balance)}{note}"


def _money(x: float) -> str:
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def _signed(x: float) -> str:
    return f"-${-x:,.2f}" if x < 0 else f"+${x:,.2f}"


def _local_time(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp


def parse_amount(text: str) -> Optional[float]:
    """A typed dollar amount ("1,500", "$250.50"), or None if it isn't one."""
    try:
        return float(text.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

_SIGN_PAIR, _FOCUS_PAIR, _GOOD_PAIR, _BAD_PAIR, _BANNER_PAIR = 1, 2, 3, 4, 5
# 256-color palette entries, where the terminal has them (else the closest of
# the basic eight: green, and white on magenta).
LIME = 118  # #87ff00
PURPLE = 91  # #8700af
BRIGHT_WHITE = 231


def _init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    rich = curses.COLORS >= 256
    curses.init_pair(_SIGN_PAIR, LIME if rich else curses.COLOR_GREEN, bg)
    curses.init_pair(_BANNER_PAIR, BRIGHT_WHITE if rich else curses.COLOR_WHITE, PURPLE if rich else curses.COLOR_MAGENTA)
    curses.init_pair(_FOCUS_PAIR, curses.COLOR_CYAN, bg)
    curses.init_pair(_GOOD_PAIR, curses.COLOR_GREEN, bg)
    curses.init_pair(_BAD_PAIR, curses.COLOR_RED, bg)


def _color(pair: int) -> int:
    return curses.color_pair(pair) if curses.has_colors() else 0


def _put(win, y: int, x: int, text: str, attr: int = 0) -> None:
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    if x < 0:
        text, x = text[-x:], 0
    available = max_x - x - 1  # curses can't write into the very last cell
    if available <= 0:
        return
    try:
        win.addstr(y, x, text[:available], attr)
    except curses.error:
        pass


def _box(win, y: int, x: int, h: int, w: int, title: str, attr: int, up: bool = False, down: bool = False) -> None:
    top = f"┌─ {title} " + "─" * (w - len(title) - 5) + "┐"
    if up:
        top = top[:-2] + "▲┐"
    bottom = "└" + "─" * (w - 2) + "┘"
    if down:
        bottom = bottom[:-2] + "▼┘"
    _put(win, y, x, top, attr)
    for row in range(1, h - 1):
        _put(win, y + row, x, "│", attr)
        _put(win, y + row, x + w - 1, "│", attr)
    _put(win, y + h - 1, x, bottom, attr)


def draw(win, floor: Floor) -> None:
    win.erase()
    height, width = win.getmaxyx()
    lay = floor.layout(height, width)
    if not lay.fits:
        msg = "Make the window bigger to step onto the casino floor"
        _put(win, height // 2, max(0, (width - len(msg)) // 2), msg, curses.A_BOLD)
        win.refresh()
        return

    for i, row in enumerate(lay.sign):
        _put(win, lay.sign_y + i, max(0, (width - len(row)) // 2), row, _color(_SIGN_PAIR) | curses.A_BOLD)
    _put(win, lay.banner_y, lay.banner_x, BANNER_TEXT.center(lay.banner_w), _color(_BANNER_PAIR) | curses.A_BOLD)

    for m, (menu, (by, bx)) in enumerate(zip(floor.menus, lay.boxes)):
        focused = floor.focus == m
        border = (_color(_FOCUS_PAIR) | curses.A_BOLD) if focused else 0
        view = menu.view
        _box(win, by, bx, lay.box_h, lay.box_w, menu.title, border, view.more_above, view.more_below)
        _put(win, by, bx + 3, menu.title, curses.A_BOLD | (_color(_FOCUS_PAIR) if focused else 0))
        for row, index in enumerate(view.visible):
            lit = focused and index == view.cursor
            text = f" {'▶' if lit else ' '} {menu.items[index].label}"
            _put(win, by + 1 + row, bx + 1, text.ljust(lay.box_w - 2), curses.A_REVERSE if lit else 0)

    left_x = lay.boxes[0][1] + 1
    _put(win, lay.status_y, left_x, "Balance:", curses.A_BOLD)
    if floor.bank is not None:
        balance = floor.bank.balance
        _put(win, lay.status_y, left_x + 9, _money(balance), _color(_GOOD_PAIR if balance >= 0 else _BAD_PAIR) | curses.A_BOLD)
    _put(win, lay.status_y, lay.leave_x, LEAVE_TEXT, curses.A_DIM)
    if floor.message:
        _put(win, lay.message_y, max(0, (width - len(floor.message)) // 2), floor.message)
    _put(win, lay.footer_y, max(0, (width - len(FOOTER)) // 2), FOOTER, curses.A_DIM)
    for i, line in enumerate(lay.notice):
        _put(win, lay.notice_y + i, max(0, (width - len(line)) // 2), line)
    win.refresh()


def _modal_frame(win, title: str, lines_h: int, box_w: int) -> Tuple[int, int, int]:
    """Draw a centered, cleared box; returns its (y, x, inner width)."""
    height, width = win.getmaxyx()
    box_w = min(box_w, width - 2)
    box_h = min(lines_h + 4, height - 1)
    y, x = max(0, (height - box_h) // 2), max(0, (width - box_w) // 2)
    for row in range(box_h):
        _put(win, y + row, x, " " * box_w)
    _box(win, y, x, box_h, box_w, title, _color(_FOCUS_PAIR) | curses.A_BOLD)
    return y, x, box_w - 4


def _wait_key(win) -> int:
    while True:
        ch = win.getch()
        if ch != curses.KEY_RESIZE:
            return ch


def show_summary(win, floor: Floor) -> None:
    rows = floor.summary_lines()
    draw(win, floor)
    y, x, inner = _modal_frame(win, "ACCOUNT SUMMARY", len(rows) + 2, 50)
    for i, (label, value) in enumerate(rows):
        attr = curses.A_BOLD if label == "Balance" else (curses.A_DIM if label.startswith("Balance =") else 0)
        _put(win, y + 2 + i, x + 2, f"{label:<{inner - 16}}{value:>16}" if value else label, attr)
    _put(win, y + 2 + len(rows) + 1, x + 2, "Press any key to return", curses.A_DIM)
    win.refresh()
    _wait_key(win)


def show_transactions(win, floor: Floor) -> None:
    lines = floor.transaction_lines()
    header = f"{'When':<17}  {'Type':<10}  {'Amount':>14}  {'Balance':>14}  Note"
    view = Viewport(len(lines), 1)
    while True:
        draw(win, floor)
        height, _ = win.getmaxyx()
        rows = max(1, min(len(lines) or 1, height - 9))
        view.resize(rows)
        y, x, inner = _modal_frame(win, "TRANSACTIONS", rows + 3, 100)
        _put(win, y + 2, x + 2, header[:inner], curses.A_BOLD)
        if not lines:
            _put(win, y + 3, x + 2, "No deposits or withdrawals yet.")
        for row, index in enumerate(view.visible):
            lit = index == view.cursor
            _put(win, y + 3 + row, x + 2, lines[index][:inner].ljust(inner), curses.A_REVERSE if lit else 0)
        more = ("▲ " if view.more_above else "  ") + ("▼" if view.more_below else " ")
        _put(win, y + 3 + rows + 1, x + 2, f"{more}  Up/Down/PgUp/PgDn scroll   Esc, q or Enter to return", curses.A_DIM)
        win.refresh()
        ch = _wait_key(win)
        moves = {curses.KEY_UP: -1, curses.KEY_DOWN: 1, curses.KEY_PPAGE: -rows, curses.KEY_NPAGE: rows,
                 curses.KEY_HOME: -len(lines), curses.KEY_END: len(lines)}
        if ch in moves:
            view.move(moves[ch])
        elif ch == curses.KEY_MOUSE:
            try:
                _, _, _, _, bstate = curses.getmouse()
            except curses.error:
                continue
            if bstate & curses.BUTTON4_PRESSED:
                view.move(-1)
            elif bstate & getattr(curses, "BUTTON5_PRESSED", 0):
                view.move(1)
            elif bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
                return
        elif ch in (27, ord("q"), ord("Q"), 10, 13, curses.KEY_ENTER):
            return


def prompt_amount(win, floor: Floor, action: str) -> None:
    """Ask for a deposit or withdrawal amount, and make it."""
    title = "DEPOSIT" if action == "deposit" else "WITHDRAW"
    hint = f"Balance {_money(floor.bank.balance)}"
    typed, error = "", ""
    curses.curs_set(1)
    try:
        while True:
            draw(win, floor)
            y, x, inner = _modal_frame(win, title, 5, 50)
            _put(win, y + 2, x + 2, hint, curses.A_DIM)
            _put(win, y + 4, x + 2, "Amount: $" + typed, curses.A_BOLD)
            _put(win, y + 5, x + 2, error[:inner], _color(_BAD_PAIR))
            _put(win, y + 6, x + 2, "Enter to confirm   Esc to cancel", curses.A_DIM)
            try:
                win.move(y + 4, x + 11 + len(typed))
            except curses.error:
                pass
            win.refresh()
            ch = _wait_key(win)
            if ch == 27:
                return
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                typed = typed[:-1]
            elif ch in (10, 13, curses.KEY_ENTER):
                amount = parse_amount(typed)
                if amount is None:
                    error = "That isn't an amount."
                    continue
                result = floor.move_money(action, amount)
                if result.startswith(("Deposited", "Withdrew")):
                    floor.message = result
                    return
                error = result
            elif 0 <= ch < 256 and (chr(ch).isdigit() or chr(ch) in ".,") and len(typed) < 15:
                typed += chr(ch)
    finally:
        curses.curs_set(0)


# --------------------------------------------------------------------------
# Running it
# --------------------------------------------------------------------------


def _floor_main(win, floor: Floor) -> Optional[Game]:
    """One visit to the floor; returns the game picked, or None to leave."""
    curses.curs_set(0)
    win.keypad(True)
    # Wait for each key. Curses hands back the same window every visit, so a
    # game's own settings (blackjack polls every 100 ms to animate) would
    # otherwise still be in force here.
    win.timeout(-1)
    _init_colors()
    escdelay = curses.get_escdelay() if hasattr(curses, "get_escdelay") else None
    if escdelay is not None:
        curses.set_escdelay(25)  # Esc clears the highlight -- don't make it wait a second
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)
    except curses.error:
        pass
    floor.open_bank()
    try:
        while True:
            draw(win, floor)
            ch = win.getch()
            action = None
            if ch == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                if bstate & curses.BUTTON4_PRESSED:
                    floor.wheel(my, mx, -1)
                elif bstate & getattr(curses, "BUTTON5_PRESSED", 0):
                    floor.wheel(my, mx, 1)
                elif bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
                    action = floor.click(my, mx)
            else:
                action = floor.key(ch)
            if action is None:
                continue
            floor.message = ""
            if action == "quit":
                return None
            if action.startswith("game:"):
                return floor.games[int(action.split(":", 1)[1])]
            if action == "summary":
                show_summary(win, floor)
            elif action == "transactions":
                show_transactions(win, floor)
            elif action in ("deposit", "withdraw"):
                prompt_amount(win, floor, action)
    finally:
        if escdelay is not None:
            curses.set_escdelay(escdelay)  # a game launched next gets the terminal exactly as it would on its own


def _exit_on_signal(signum, _frame) -> None:
    raise SystemExit(128 + signum)


def run() -> None:
    """Open the casino floor; each game picked there runs until it's quit,
    then it's back to the floor, until the player leaves."""
    for name in ("SIGHUP", "SIGTERM"):  # leave curses cleanly on a closed window or a plain kill
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, _exit_on_signal)
    try:
        sys.stdout.write("\x1b[9;1t")  # ask the terminal to maximize, as the games do
        sys.stdout.flush()
    except Exception:  # pragma: no cover - a closed stdout just means no maximize
        pass
    floor = Floor()
    while True:
        game = curses.wrapper(_floor_main, floor)
        if game is None:
            return
        game.launch()
        floor.message = f"Back on the floor from {game.name}."
