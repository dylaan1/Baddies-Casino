"""The casino floor: Baddie's Casino's title screen, and where every game
starts.

    python3 -m casino

A marquee runs round the very edge of the screen: green and red lights,
two dark cells apart, chasing clockwise like an old Vegas sign
(casino/marquee.py). Inside it, a blank row, then the BADDIE'S CASINO sign on
one line in lime-green block letters, one and a half times their original
size, over a lime-green banner -- "Luxury Gaming & Amenities | Making Your
Dreams Come True One Bet At A Time" in black. Under them sit the menus: GAMES
on the left, to sit down at a game; on the right, BANK -- the casino bank
everything plays from (casino/bank.py): its summary and transaction list,
and deposits and withdrawals -- with DATA beneath it, for each game's
Historical Session Data and P/L Charts (casino/data_views.py). The bottom 15%
of the screen holds no tables: just the balance, any message, the keys, and
the intellectual-property notice on its purple strip.

Up/Down move through a menu and stop at its ends, so the highlight never
falls off -- except that BANK runs on into DATA below it, and DATA back up
into BANK; a menu longer than its box scrolls to keep the highlight in view.
Left/Right switch sides, Tab goes round all three menus, Enter picks the
highlighted option (so does clicking it once it's highlighted), and q leaves
the casino. Clicking anywhere off the menus clears the highlight; an arrow key
or a click on an option brings it back.

A game runs exactly as it does on its own (python3 -m blackjack): the floor
steps out of curses and the game takes over the terminal. Every game leaves
the same two ways: 'exit' saves and comes back to the floor (even for a game
started on its own), and 'quit' saves and closes Baddie's Casino.
"""
from __future__ import annotations

import curses
import math
import signal
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import data_views, tui
from .bank import Bank, Opening
from .marquee import Marquee
from .records import PLHistory, SessionRecord, money, signed
from .tui import Viewport

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
}
SIGN_TEXT = "BADDIE'S CASINO"
BLOCK = "█"
# A terminal row split into a top and a bottom half: (top filled, bottom filled) -> character.
_HALF_BLOCKS = {(True, True): BLOCK, (True, False): "▀", (False, True): "▄", (False, False): " "}


# The sizes the sign comes in, biggest first: (columns, half-rows) per font
# cell, and the columns between letters (words are five times that apart, as
# in the font's own spacing). A terminal cell is about twice as tall as it is
# wide, so a cell as many half-rows tall as it is columns wide keeps the
# letters' shape: (2, 2) is the original size -- 2 columns by 1 row -- and
# (3, 3) one and a half times it, its half rows drawn with half blocks.
SIGN_SIZES = (
    (3, 3, 3),  # 1.5x: 237 columns wide, 8 rows tall
    (3, 3, 2),  # 1.5x, letters 2 columns apart: 220 wide
    (3, 3, 1),  # 1.5x, letters 1 column apart: 203 wide
    (2, 2, 2),  # the original size: 158 wide, 5 rows
    (1, 2, 1),  # compact: 79 wide
)
SIGN_MARGIN = 4  # columns kept clear on either side of the sign, at the least


def sign_rows(text: str, cell_w: int, cell_h: int, gap: int) -> List[str]:
    """`text` in block letters, each font cell `cell_w` columns wide and
    `cell_h` half-rows tall, letters `gap` columns apart and words `5 * gap`."""
    half_rows: List[str] = []
    for row in range(5):
        words = [
            (" " * gap).join("".join(("#" if px == "#" else " ") * cell_w for px in _FONT[ch][row]) for ch in word)
            for word in text.split(" ")
        ]
        half_rows += [(" " * (5 * gap)).join(words)] * cell_h
    if len(half_rows) % 2:
        half_rows.append(" " * len(half_rows[0]))
    return [
        "".join(_HALF_BLOCKS[(top == "#", bottom == "#")] for top, bottom in zip(upper, lower))
        for upper, lower in zip(half_rows[0::2], half_rows[1::2])
    ]


def fit_sign(width: int, height: int) -> List[str]:
    """The biggest version of the sign that fits in `width` x `height` on one
    line, with SIGN_MARGIN clear on either side -- in a window too narrow for
    any of them, BADDIE'S over CASINO, and in a tiny one the name in plain
    text."""
    first, second = SIGN_TEXT.split(" ")
    one_line = [sign_rows(SIGN_TEXT, *size) for size in SIGN_SIZES]
    stacked = [sign_rows(first, *size) + [""] + sign_rows(second, *size) for size in SIGN_SIZES[-2:]]
    for rows in one_line + stacked:
        if max(len(r) for r in rows) <= width - 2 * SIGN_MARGIN and len(rows) <= height:
            return rows
    return [SIGN_TEXT]


# --------------------------------------------------------------------------
# Menus
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MenuItem:
    label: str
    action: str  # what picking it does -- see _floor_main


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
    # Runs the game in the terminal, as its own `python3 -m` would, until the
    # player leaves: returns "quit" to close the casino, else ("floor", for
    # 'exit') it's back to the floor.
    launch: Callable[[], Optional[str]]
    # Its history, for the DATA menu (casino/records.py): every session, and
    # its P/L round by round. A game without one shows nothing recorded.
    sessions: Optional[Callable[[], List[SessionRecord]]] = None
    pl_history: Optional[Callable[[], PLHistory]] = None


def blackjack_game(db_path: Optional[Path] = None) -> Game:
    """Classic Blackjack, on its default history database or on `db_path`
    (python3 -m blackjack --db FILE, then 'exit' to the floor)."""

    def launch() -> str:
        from blackjack.ui import run

        return run(db_path)

    def sessions() -> List[SessionRecord]:
        from blackjack import records

        return records.sessions(db_path)

    def pl_history() -> PLHistory:
        from blackjack import records

        return records.pl_history(db_path)

    return Game("Classic Blackjack", "blackjack", launch, sessions, pl_history)


def _blackjack_opening() -> Opening:
    # Blackjack kept the bankroll itself before the bank existed: the first
    # time the bank is opened, from here or from the game, it starts from that.
    from blackjack.bank import opening

    return opening()


# Every game on the floor, in menu order -- a new game is one more entry.
GAMES: List[Game] = [blackjack_game()]
BANK_ITEMS = [
    MenuItem("Account Summary", "summary"),
    MenuItem("Deposit", "deposit"),
    MenuItem("Withdraw", "withdraw"),
    MenuItem("Transactions", "transactions"),
]
DATA_ITEMS = [
    MenuItem("Historical Session Data", "data:sessions"),
    MenuItem("P/L Charts", "data:charts"),
]
GAMES_MENU, BANK_MENU, DATA_MENU = 0, 1, 2
# The menus' places on the floor: GAMES on the left; BANK over DATA on the right.
COLUMNS: Tuple[Tuple[int, ...], ...] = ((GAMES_MENU,), (BANK_MENU, DATA_MENU))

# A terminal can't measure inches, so the floor's margins are set in columns
# per inch: about 21 for Monaco 10 pt on a 13-inch MacBook Pro at its default
# scaled resolution. A different font size or display scaling changes it.
COLUMNS_PER_INCH = 21
BANNER_MARGIN_IN = 3  # inches clear on either side of the banner
MENU_MARGIN_IN = 1  # inches between each column of menus and its side of the screen
MENU_GAP = 4  # columns between the two columns of menus
MENU_STACK_GAP = 1  # rows between BANK and DATA
MIN_MENU_W = 28  # room for " ▶ Historical Session Data" inside the box
MIN_MENU_ROWS = 4  # options a menu shows before the sign is made smaller to fit them; past this, menus scroll
BOTTOM_CLEAR = 0.15  # the bottom 15% of the screen holds no tables
EDGE = 1  # the marquee's rows and columns, round the outside, that nothing else uses
BANNER_TEXT = "Luxury Gaming & Amenities | Making Your Dreams Come True One Bet At A Time"
LEAVE_TEXT = "q  Leave Casino"
FOOTER = "↑↓ choose   ←→ switch side   Tab next menu   Enter select   click away to clear   q leave"
SHORT_FOOTER = "↑↓ choose  ←→ side  Tab menu  Enter select  q leave"  # for a window too narrow for FOOTER
NOTICE = (
    "Intellectual Property of Dylan Behseresht, 2026. Any unauthorized redistribution of this software without "
    "express written consent is expressly prohibited."
)

Rect = Tuple[int, int, int, int]  # (y, x, height, width)


@dataclass
class Layout:
    """Where everything on the floor goes for one window size."""

    sign: List[str]
    sign_y: int
    banner_y: int
    banner_x: int
    banner_w: int
    rects: List[Rect]  # each menu's box, by menu: GAMES, BANK, DATA
    status_y: int  # balance (left) and LEAVE_TEXT (right), just under the boxes
    message_y: int
    leave_x: int
    footer_y: int  # the keys
    notice: List[str]  # NOTICE, as one line or (in a narrow window) wrapped
    notice_y: int  # the row its first line is on: the last ones end just above the marquee
    fits: bool = True


class Floor:
    """The floor's state and what each key or click does to it, apart from
    drawing -- so it can be exercised without a terminal."""

    def __init__(self, games: Optional[List[Game]] = None, bank_opener: Optional[Callable[[], Bank]] = None):
        self.games = list(GAMES if games is None else games)
        self.menus = [
            Menu("GAMES", [MenuItem(g.name, f"game:{i}") for i, g in enumerate(self.games)], MIN_MENU_ROWS),
            Menu("BANK", list(BANK_ITEMS), len(BANK_ITEMS)),
            Menu("DATA", list(DATA_ITEMS), len(DATA_ITEMS)),
        ]
        self.focus: Optional[int] = GAMES_MENU  # the menu holding the highlight, or None once it's been clicked off
        self.last_focus = GAMES_MENU
        self._last_in_column = [col[0] for col in COLUMNS]  # the menu last used on each side
        self.message = ""
        self.marquee = Marquee()
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
        """Inside the marquee (the outermost rows and columns), top to
        bottom: a blank row, the sign, a blank row, the banner, a blank row,
        then the menus down to where the bottom 15% of the screen begins --
        GAMES down the left; BANK, just tall enough for its options, over DATA
        on the right, the two ending level. That bottom stretch holds the
        status row (balance, Leave Casino), the message row, the keys, and
        the notice just above the marquee. Across, each side's menus run from
        MENU_MARGIN_IN inches in from the screen's edge to MENU_GAP columns
        from the other side's, and the banner keeps BANNER_MARGIN_IN inches
        clear on either side. In a smaller window the sign shrinks first,
        then the margins; menus with more options than room scroll."""
        inch = COLUMNS_PER_INCH
        notice = textwrap.wrap(NOTICE, max(20, width - 6))
        # kept clear of tables: status, message, keys, the notice, the marquee
        bottom = max(4 + len(notice), math.ceil(height * BOTTOM_CLEAR))
        box_last = height - bottom - 1  # the last row a box may use

        sides = len(COLUMNS)
        margin = min(MENU_MARGIN_IN * inch, max(EDGE + 1, (width - (sides - 1) * MENU_GAP - sides * MIN_MENU_W) // 2))
        box_w = (width - 2 * margin - (sides - 1) * MENU_GAP) // sides
        xs = [margin + i * (box_w + MENU_GAP) for i in range(sides - 1)] + [width - margin - box_w]

        banner_margin = min(BANNER_MARGIN_IN * inch, max(EDGE + 1, (width - len(BANNER_TEXT) - 6) // 2))

        sign_y = EDGE + 1
        sign = fit_sign(width, (box_last + 1) - sign_y - 3 - (MIN_MENU_ROWS + 2))  # 3: blank, banner, blank
        banner_y = sign_y + len(sign) + 1
        box_y = banner_y + 2
        column_h = box_last - box_y + 1

        bank_rows = len(self.menus[BANK_MENU].items)
        data_min = len(self.menus[DATA_MENU].items) + 2
        bank_h = max(3, min(bank_rows + 2, column_h - MENU_STACK_GAP - data_min))
        data_y = box_y + bank_h + MENU_STACK_GAP
        rects = [
            (box_y, xs[0], column_h, box_w),
            (box_y, xs[1], bank_h, box_w),
            (data_y, xs[1], box_last - data_y + 1, box_w),
        ]
        for menu, (_, _, h, _) in zip(self.menus, rects):
            menu.view.resize(h - 2)
        lay = Layout(
            sign=sign,
            sign_y=sign_y,
            banner_y=banner_y,
            banner_x=banner_margin,
            banner_w=width - 2 * banner_margin,
            rects=rects,
            status_y=box_last + 1,
            message_y=box_last + 2,
            leave_x=xs[-1] + box_w - len(LEAVE_TEXT) - 1,
            footer_y=height - EDGE - len(notice) - 1,
            notice=notice,
            notice_y=height - EDGE - len(notice),
            fits=box_w >= MIN_MENU_W and min(h for _, _, h, _ in rects) >= 3,
        )
        self.layout_cache = lay
        return lay

    def item_at(self, y: int, x: int) -> Optional[Tuple[int, Optional[int]]]:
        """(menu, option) under a screen position -- option None on the box's
        border or title -- else None (off the menus)."""
        lay = self.layout_cache
        if lay is None:
            return None
        for m, (by, bx, bh, bw) in enumerate(lay.rects):
            if by <= y < by + bh and bx <= x < bx + bw:
                row = y - by - 1
                view = self.menus[m].view
                if 0 <= row < view.rows and view.top + row < view.count and 0 < x - bx < bw - 1:
                    return m, view.top + row
                return m, None
        return None

    # ---- input ----

    @staticmethod
    def _column(menu: int) -> int:
        return next(i for i, col in enumerate(COLUMNS) if menu in col)

    def _refocus(self, menu: Optional[int] = None) -> None:
        self.focus = self.last_focus if menu is None else menu
        self.last_focus = self.focus
        self._last_in_column[self._column(self.focus)] = self.focus

    def _step(self, direction: int) -> None:
        """Up (-1) or Down (1) in the focused menu -- past its last option
        into the menu below it on that side, past its first into the one
        above (BANK and DATA); anywhere else the highlight stops at the end."""
        view = self.menus[self.focus].view
        column = COLUMNS[self._column(self.focus)]
        place = column.index(self.focus)
        if direction > 0 and view.cursor == view.count - 1 and place + 1 < len(column):
            self._refocus(column[place + 1])
            self.menus[self.focus].view.home()
        elif direction < 0 and view.cursor == 0 and place > 0:
            self._refocus(column[place - 1])
            self.menus[self.focus].view.end()
        else:
            view.move(direction)

    def key(self, ch: int) -> Optional[str]:
        """Apply a key press; returns the action to perform, if any."""
        if ch in (ord("q"), ord("Q")):
            return "quit"
        if ch == 27:  # Esc: same as clicking off
            self.focus = None
            return None
        if self.focus is None and ch in (curses.KEY_LEFT, curses.KEY_RIGHT, 9, curses.KEY_BTAB, curses.KEY_UP,
                                         curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE, curses.KEY_HOME,
                                         curses.KEY_END):
            self._refocus()  # the first key after clicking off just brings the highlight back
            return None
        if self.focus is None:
            return None
        if ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
            side = max(0, min(len(COLUMNS) - 1, self._column(self.focus) + (-1 if ch == curses.KEY_LEFT else 1)))
            self._refocus(self._last_in_column[side])
            return None
        if ch in (9, curses.KEY_BTAB):  # Tab / Shift-Tab go round every menu
            self._refocus((self.focus + (1 if ch == 9 else -1)) % len(self.menus))
            return None
        if ch in (curses.KEY_UP, curses.KEY_DOWN):
            self._step(-1 if ch == curses.KEY_UP else 1)
            return None
        if self.menus[self.focus].view.key(ch):  # PgUp/PgDn/Home/End, within the menu
            return None
        if ch in (10, 13, curses.KEY_ENTER, ord(" ")):
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
        """Scroll wheel over a menu: move the highlight a row, as Up/Down do."""
        hit = self.item_at(y, x)
        if hit is not None:
            self._refocus(hit[0])
            self._step(direction)

    # ---- the bank's figures, as the floor shows them ----

    def summary_lines(self) -> List[Tuple[str, str]]:
        bank = self.bank
        rows = [("Balance", money(bank.balance)), ("", "")]
        rows.append(("Won at the games", signed(bank.total_winnings)))
        names = {g.bank_key: g.name for g in self.games}
        for key in list(names) + sorted(k for k in bank.game_winnings if k not in names):
            rows.append((f"  {names.get(key, key.title())}", signed(bank.game_winnings.get(key, 0.0))))
        rows += [
            ("Deposited", money(bank.deposited)),
            ("Withdrawn", money(bank.withdrawn)),
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
                f"{data_views.local_time(t.get('at', '')):<17}  {kind:<10}  {signed(float(t.get('amount', 0))):>14}  "
                f"{money(float(t.get('balance', 0))):>14}  {t.get('note', '')}"
            )
        return lines

    def move_money(self, action: str, amount: float) -> str:
        """A deposit or withdrawal from the floor; returns the message to show."""
        bank = self.bank
        if amount <= 0:
            return "Enter an amount above $0."
        if action == "withdraw" and amount > bank.balance + 1e-9:
            return f"You can withdraw at most {money(max(bank.balance, 0.0))}."
        ok = bank.deposit(amount, "Casino floor") if action == "deposit" else bank.withdraw(amount, "Casino floor")
        verb = "Deposited" if action == "deposit" else "Withdrew"
        note = "" if ok else f" (but the bank file couldn't be saved: {bank.error})"
        return f"{verb} {money(amount)} -- balance {money(bank.balance)}{note}"


def parse_amount(text: str) -> Optional[float]:
    """A typed dollar amount ("1,500", "$250.50"), or None if it isn't one."""
    try:
        return float(text.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


def draw(win, floor: Floor) -> None:
    win.erase()
    height, width = win.getmaxyx()
    lay = floor.layout(height, width)
    if not lay.fits:
        msg = "Make the window bigger to step onto the casino floor"
        tui.put(win, height // 2, max(0, (width - len(msg)) // 2), msg, curses.A_BOLD)
        floor.marquee.draw(win)
        win.refresh()
        return

    for i, row in enumerate(lay.sign):
        tui.put(win, lay.sign_y + i, max(0, (width - len(row)) // 2), row, tui.color(tui.SIGN) | curses.A_BOLD)
    tui.put(win, lay.banner_y, lay.banner_x, BANNER_TEXT.center(lay.banner_w), tui.color(tui.BANNER) | curses.A_BOLD)

    for m, (menu, (by, bx, bh, bw)) in enumerate(zip(floor.menus, lay.rects)):
        focused = floor.focus == m
        border = (tui.color(tui.FOCUS) | curses.A_BOLD) if focused else 0
        view = menu.view
        tui.box(win, by, bx, bh, bw, menu.title, border, view.more_above, view.more_below)
        tui.put(win, by, bx + 3, menu.title, curses.A_BOLD | (tui.color(tui.FOCUS) if focused else 0))
        for row, index in enumerate(view.visible):
            lit = focused and index == view.cursor
            text = f" {'▶' if lit else ' '} {menu.items[index].label}"
            tui.put(win, by + 1 + row, bx + 1, text.ljust(bw - 2)[: bw - 2], curses.A_REVERSE if lit else 0)

    left_x = lay.rects[GAMES_MENU][1] + 1
    tui.put(win, lay.status_y, left_x, "Balance:", curses.A_BOLD)
    if floor.bank is not None:
        balance = floor.bank.balance
        tui.put(win, lay.status_y, left_x + 9, money(balance), tui.color(tui.GOOD if balance >= 0 else tui.BAD) | curses.A_BOLD)
    tui.put(win, lay.status_y, lay.leave_x, LEAVE_TEXT, curses.A_DIM)
    if floor.message:
        tui.put(win, lay.message_y, max(0, (width - len(floor.message)) // 2), floor.message)
    footer = FOOTER if len(FOOTER) <= width - 4 else SHORT_FOOTER
    tui.put(win, lay.footer_y, max(EDGE + 1, (width - len(footer)) // 2), footer[: width - 4], curses.A_DIM)
    for i, line in enumerate(lay.notice):
        strip = f" {line} "  # the purple strip runs the length of the text, a space either side
        tui.put(win, lay.notice_y + i, max(EDGE + 1, (width - len(strip)) // 2), strip, tui.color(tui.NOTICE) | curses.A_BOLD)
    floor.marquee.draw(win)
    win.refresh()


def show_summary(win, floor: Floor) -> None:
    rows = floor.summary_lines()

    def redraw() -> None:
        draw(win, floor)
        y, x, inner = tui.modal_frame(win, "ACCOUNT SUMMARY", len(rows) + 2, 50)
        for i, (label, value) in enumerate(rows):
            attr = curses.A_BOLD if label == "Balance" else (curses.A_DIM if label.startswith("Balance =") else 0)
            tui.put(win, y + 2 + i, x + 2, f"{label:<{inner - 16}}{value:>16}" if value else label, attr)
        tui.put(win, y + 2 + len(rows) + 1, x + 2, "Press any key to return", curses.A_DIM)
        floor.marquee.draw(win)
        win.refresh()

    redraw()
    tui.wait_key(win, floor.marquee, redraw)


def show_transactions(win, floor: Floor) -> None:
    lines = floor.transaction_lines()
    header = f"{'When':<17}  {'Type':<10}  {'Amount':>14}  {'Balance':>14}  Note"
    view = Viewport(len(lines), 1)
    while True:
        draw(win, floor)
        height, _ = win.getmaxyx()
        rows = max(1, min(len(lines) or 1, height - 12))
        view.resize(rows)
        y, x, inner = tui.modal_frame(win, "TRANSACTIONS", rows + 3, 100)
        tui.put(win, y + 2, x + 2, header[:inner], curses.A_BOLD)
        if not lines:
            tui.put(win, y + 3, x + 2, "No deposits or withdrawals yet.")
        for row, index in enumerate(view.visible):
            lit = index == view.cursor
            tui.put(win, y + 3 + row, x + 2, lines[index][:inner].ljust(inner), curses.A_REVERSE if lit else 0)
        more = ("▲ " if view.more_above else "  ") + ("▼" if view.more_below else " ")
        tui.put(win, y + 3 + rows + 1, x + 2, f"{more}  Up/Down/PgUp/PgDn scroll   Esc, q or Enter to return", curses.A_DIM)
        floor.marquee.draw(win)
        win.refresh()
        ch = tui.getch(win, floor.marquee)
        if view.key(ch):
            continue
        if ch == curses.KEY_MOUSE:
            event = tui.mouse()
            if event is None:
                continue
            if tui.wheel(event[2]):
                view.move(tui.wheel(event[2]))
            elif tui.clicked(event[2]):
                return
        elif ch in tui.BACK_KEYS + tui.ENTER_KEYS:
            return


def prompt_amount(win, floor: Floor, action: str) -> None:
    """Ask for a deposit or withdrawal amount, and make it."""
    title = "DEPOSIT" if action == "deposit" else "WITHDRAW"
    hint = f"Balance {money(floor.bank.balance)}"
    typed, error = "", ""
    curses.curs_set(1)
    try:
        while True:
            draw(win, floor)
            y, x, inner = tui.modal_frame(win, title, 5, 50)
            tui.put(win, y + 2, x + 2, hint, curses.A_DIM)
            tui.put(win, y + 4, x + 2, "Amount: $" + typed, curses.A_BOLD)
            tui.put(win, y + 5, x + 2, error[:inner], tui.color(tui.BAD))
            tui.put(win, y + 6, x + 2, "Enter to confirm   Esc to cancel", curses.A_DIM)
            floor.marquee.draw(win)
            caret = (y + 4, x + 11 + len(typed))
            try:
                win.move(*caret)
            except curses.error:
                pass
            win.refresh()
            ch = tui.getch(win, floor.marquee, caret)
            if ch == 27:
                return
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                typed = typed[:-1]
            elif ch in tui.ENTER_KEYS:
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


def open_data(win, floor: Floor, action: str) -> None:
    """DATA: choose a game, then show its sessions or its P/L chart."""
    which = "HISTORICAL SESSION DATA" if action == "data:sessions" else "P/L CHARTS"
    backdrop = lambda: draw(win, floor)  # noqa: E731
    game = data_views.pick_game(win, floor, which, backdrop)
    if game is None:
        return
    if action == "data:sessions":
        data_views.show_sessions(win, floor, game, backdrop)
    else:
        data_views.show_chart(win, floor, game, backdrop)


# --------------------------------------------------------------------------
# Running it
# --------------------------------------------------------------------------


def _floor_main(win, floor: Floor) -> Optional[Game]:
    """One visit to the floor; returns the game picked, or None to leave."""
    curses.curs_set(0)
    win.keypad(True)
    tui.init_colors()
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
            # (getch sets its own wait each time, so a game's own settings --
            # blackjack polls every 100 ms to animate -- never carry over)
            ch = tui.getch(win, floor.marquee)
            action = None
            if ch == curses.KEY_MOUSE:
                event = tui.mouse()
                if event is None:
                    continue
                my, mx, bstate = event
                if tui.wheel(bstate):
                    floor.wheel(my, mx, tui.wheel(bstate))
                elif tui.clicked(bstate):
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
            elif action.startswith("data:"):
                open_data(win, floor, action)
    finally:
        if escdelay is not None:
            curses.set_escdelay(escdelay)  # a game launched next gets the terminal exactly as it would on its own


def _exit_on_signal(signum, _frame) -> None:
    raise SystemExit(128 + signum)


def run(games: Optional[List[Game]] = None) -> None:
    """Open the casino floor. Each game picked there runs until the player
    leaves it: 'exit' comes back to the floor, 'quit' closes the casino -- as
    does leaving the floor itself. `games` stands in for GAMES."""
    for name in ("SIGHUP", "SIGTERM"):  # leave curses cleanly on a closed window or a plain kill
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, _exit_on_signal)
    try:
        sys.stdout.write("\x1b[9;1t")  # ask the terminal to maximize, as the games do
        sys.stdout.flush()
    except Exception:  # pragma: no cover - a closed stdout just means no maximize
        pass
    floor = Floor(games)
    while True:
        game = curses.wrapper(_floor_main, floor)
        if game is None or game.launch() == "quit":
            return
        floor.message = f"Back on the floor from {game.name}."
