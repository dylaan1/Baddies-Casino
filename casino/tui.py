"""The casino floor's drawing pieces, shared by the floor itself
(casino/floor.py) and its DATA windows (casino/data_views.py): colors,
writing text that never trips curses up, boxes, scrolling lists, and waiting
for a key while the marquee lights keep moving (casino/marquee.py)."""
from __future__ import annotations

import curses
from typing import Callable, Optional, Tuple

# Color pairs.
SIGN, FOCUS, GOOD, BAD, NOTICE, BANNER, BULB_GREEN, BULB_RED = range(1, 9)
# 256-color palette entries, where the terminal has them (else the closest of the basic eight).
LIME = 118  # #87ff00 -- the sign, and the banner under it
PURPLE = 91  # #8700af -- behind the notice
BRIGHT_WHITE = 231
BLACK = 16
BRIGHT_GREEN = 46  # #00ff00 -- marquee bulbs
BRIGHT_RED = 196  # #ff0000


def init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    rich = curses.COLORS >= 256
    curses.init_pair(SIGN, LIME if rich else curses.COLOR_GREEN, bg)
    curses.init_pair(BANNER, BLACK if rich else curses.COLOR_BLACK, LIME if rich else curses.COLOR_GREEN)
    curses.init_pair(NOTICE, BRIGHT_WHITE if rich else curses.COLOR_WHITE, PURPLE if rich else curses.COLOR_MAGENTA)
    curses.init_pair(FOCUS, curses.COLOR_CYAN, bg)
    curses.init_pair(GOOD, curses.COLOR_GREEN, bg)
    curses.init_pair(BAD, curses.COLOR_RED, bg)
    curses.init_pair(BULB_GREEN, BRIGHT_GREEN if rich else curses.COLOR_GREEN, bg)
    curses.init_pair(BULB_RED, BRIGHT_RED if rich else curses.COLOR_RED, bg)


def color(pair: int) -> int:
    return curses.color_pair(pair) if curses.has_colors() else 0


def put(win, y: int, x: int, text: str, attr: int = 0) -> None:
    """Write `text` at (y, x), clipped to the window, and never into its last
    column (that's the marquee's -- and curses can't write the very last
    cell anyway)."""
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    if x < 0:
        text, x = text[-x:], 0
    available = max_x - x - 1
    if available <= 0:
        return
    try:
        win.addstr(y, x, text[:available], attr)
    except curses.error:
        pass


def put_cell(win, y: int, x: int, ch: str, attr: int = 0) -> None:
    """One character anywhere, the last column included (for the marquee)."""
    try:
        win.addstr(y, x, ch, attr)
    except curses.error:  # the bottom-right cell: written, but the cursor can't move past it
        pass


def box(win, y: int, x: int, h: int, w: int, title: str, attr: int, up: bool = False, down: bool = False) -> None:
    top = f"┌─ {title} " + "─" * max(0, w - len(title) - 5) + "┐"
    if up:
        top = top[:-2] + "▲┐"
    bottom = "└" + "─" * (w - 2) + "┘"
    if down:
        bottom = bottom[:-2] + "▼┘"
    put(win, y, x, top, attr)
    for row in range(1, h - 1):
        put(win, y + row, x, "│", attr)
        put(win, y + row, x + w - 1, "│", attr)
    put(win, y + h - 1, x, bottom, attr)


def clear_area(win, y: int, x: int, h: int, w: int) -> None:
    for row in range(h):
        put(win, y + row, x, " " * w)


def modal_frame(win, title: str, lines_h: int, box_w: int) -> Tuple[int, int, int]:
    """Draw a centered, cleared box, inside the marquee; returns its (y, x,
    inner width)."""
    height, width = win.getmaxyx()
    box_w = max(10, min(box_w, width - 6))
    box_h = max(3, min(lines_h + 4, height - 4))
    y, x = max(2, (height - box_h) // 2), max(3, (width - box_w) // 2)
    clear_area(win, y, x, box_h, box_w)
    box(win, y, x, box_h, box_w, title, color(FOCUS) | curses.A_BOLD)
    return y, x, box_w - 4


def window_rect(win) -> Tuple[int, int, int, int]:
    """(y, x, height, width) of a full window: everything inside the marquee,
    with a blank row and column between."""
    height, width = win.getmaxyx()
    return 2, 2, max(3, height - 4), max(10, width - 4)


def getch(win, marquee, caret: Optional[Tuple[int, int]] = None) -> int:
    """The next key, mouse or resize event -- moving the marquee lights along
    each time one doesn't come within a step. `caret` is where the cursor
    belongs while it's showing (in a text prompt)."""
    win.timeout(marquee.step_ms)
    while True:
        ch = win.getch()
        if ch != -1:
            return ch
        marquee.advance()
        marquee.draw(win)
        if caret is not None:
            try:
                win.move(*caret)
            except curses.error:
                pass
        win.refresh()


def wait_key(win, marquee, redraw: Callable[[], None]) -> int:
    """The next key or mouse event (a resize just redraws)."""
    while True:
        ch = getch(win, marquee)
        if ch != curses.KEY_RESIZE:
            return ch
        redraw()


def mouse() -> Optional[Tuple[int, int, int]]:
    """The mouse event just read: (y, x, button state), or None."""
    try:
        _, mx, my, _, bstate = curses.getmouse()
    except curses.error:
        return None
    return my, mx, bstate


def clicked(bstate: int) -> bool:
    return bool(bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED))


def wheel(bstate: int) -> int:
    """-1 for the wheel turned up, 1 for down, 0 for neither."""
    if bstate & curses.BUTTON4_PRESSED:
        return -1
    if bstate & getattr(curses, "BUTTON5_PRESSED", 0):
        return 1
    return 0


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

    def key(self, ch: int) -> bool:
        """Move for a scrolling key; True if it was one."""
        moves = {
            curses.KEY_UP: lambda: self.move(-1),
            curses.KEY_DOWN: lambda: self.move(1),
            curses.KEY_PPAGE: lambda: self.page(-1),
            curses.KEY_NPAGE: lambda: self.page(1),
            curses.KEY_HOME: self.home,
            curses.KEY_END: self.end,
        }
        if ch in moves:
            moves[ch]()
            return True
        return False


ENTER_KEYS = (10, 13, curses.KEY_ENTER)
BACK_KEYS = (27, ord("q"), ord("Q"))
