"""The casino floor's marquee: lights chasing clockwise around the outermost
cells of the screen, like an old Vegas sign.

The lights sit every third cell along the edge -- a light, then two dark
cells -- alternating bright green and bright red, and every step they all
move one cell clockwise (along the top to the right, down the right side,
back along the bottom, up the left side).

For the lights to come round evenly, the cells they run along have to number
a multiple of six (green, two dark, red, two dark). So the four corners stay
dark, and so do up to five more cells beside them as needed -- going round a
corner, a light just skips one cell -- and there's never a seam where two
greens meet or the spacing breaks, whatever the window's size.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from . import tui

STEP_MS = 150  # how often the lights move a cell
SPACING = 3  # a light, then two dark cells
GREEN, RED = "green", "red"
BULB = "█"

Cell = Tuple[int, int]


def track(height: int, width: int) -> List[Cell]:
    """Every outermost cell, clockwise from the top-left corner."""
    if height < 3 or width < 3:
        return []
    top = [(0, x) for x in range(width)]
    right = [(y, width - 1) for y in range(1, height)]
    bottom = [(height - 1, x) for x in range(width - 2, -1, -1)]
    left = [(y, 0) for y in range(height - 2, 0, -1)]
    return top + right + bottom + left


def slots(height: int, width: int) -> List[Cell]:
    """The cells the lights run along, clockwise: the track without its
    corners, and without as many cells beside them as it takes to leave a
    multiple of six."""
    cells = track(height, width)
    if not cells:
        return []
    corners = [0, width - 1, (width - 1) + (height - 1), 2 * (width - 1) + (height - 1)]
    extra = (len(cells) - len(corners)) % (2 * SPACING)
    beside = [c + 1 for c in corners] + [c + 2 for c in corners]
    dark = set(corners) | set(beside[:extra])
    return [cell for i, cell in enumerate(cells) if i not in dark]


def lights(height: int, width: int, step: int) -> Dict[Cell, str]:
    """Which cells are lit at `step`, and in which color."""
    run = slots(height, width)
    lit: Dict[Cell, str] = {}
    for i, cell in enumerate(run):
        k = (i - step) % len(run)
        if k % SPACING == 0:
            lit[cell] = GREEN if (k // SPACING) % 2 == 0 else RED
    return lit


class Marquee:
    def __init__(self, step_ms: int = STEP_MS):
        self.step_ms = step_ms
        self.step = 0

    def advance(self) -> None:
        self.step += 1

    def draw(self, win) -> None:
        height, width = win.getmaxyx()
        lit = lights(height, width, self.step)
        attrs = {GREEN: tui.color(tui.BULB_GREEN), RED: tui.color(tui.BULB_RED)}
        for y, x in track(height, width):
            color = lit.get((y, x))
            tui.put_cell(win, y, x, BULB if color else " ", (attrs[color] | tui.curses.A_BOLD) if color else 0)
