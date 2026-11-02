"""Line charts in a terminal, drawn with braille characters: each one is a
2 x 4 grid of dots, so a chart `cols` characters wide and `rows` tall has
2 * cols by 4 * rows dots to draw its line with. Pure text -- the casino
floor's P/L Charts window (casino/data_views.py) colors and frames it."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

BLANK = "⠀"  # the braille character with no dots
# The dot at (row, column) of a braille character's 4 x 2 grid -> its bit.
_DOTS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


@dataclass
class Chart:
    cells: List[str]  # `rows` strings of `cols` braille characters, top row first
    lo: float  # the value at the bottom edge
    hi: float  # ... and at the top
    ticks: List[Tuple[int, float]]  # (row, value) for each label up the side
    zero_row: Optional[int]  # the row $0 falls in, if it's in range


def nice_step(span: float, count: int) -> float:
    """A round step (1, 2, 2.5 or 5 times a power of ten) that splits `span`
    into about `count` parts."""
    if span <= 0:
        return 1.0
    raw = span / max(count, 1)
    power = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * power:
            return m * power
    return 10 * power


def line_chart(values: Sequence[float], rows: int, cols: int, labels: int = 5) -> Chart:
    """`values` (oldest first) as a line across `cols` x `rows`. The range
    always takes in $0 and runs a little past the highest and lowest values;
    the labels up the side go at round steps inside it."""
    rows, cols = max(1, rows), max(1, cols)
    lo, hi = min(min(values, default=0.0), 0.0), max(max(values, default=0.0), 0.0)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.04, hi + span * 0.04
    step = nice_step(span, min(labels, max(rows // 2, 1)))
    dots_w, dots_h = 2 * cols, 4 * rows

    def dot_y(v: float) -> int:
        return round((hi - v) / (hi - lo) * (dots_h - 1))

    grid = [[False] * dots_w for _ in range(dots_h)]
    n = len(values)
    points = [(round(i * (dots_w - 1) / max(n - 1, 1)), dot_y(v)) for i, v in enumerate(values)]
    for (x0, y0), (x1, y1) in zip(points, points[1:] or points):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for s in range(steps + 1):
            grid[round(y0 + (y1 - y0) * s / steps)][round(x0 + (x1 - x0) * s / steps)] = True

    cells = []
    for r in range(rows):
        line = []
        for c in range(cols):
            bits = 0
            for dy in range(4):
                for dx in range(2):
                    if grid[4 * r + dy][2 * c + dx]:
                        bits |= _DOTS[dy][dx]
            line.append(chr(0x2800 + bits))
        cells.append("".join(line))

    ticks: List[Tuple[int, float]] = []
    value = math.ceil(lo / step) * step
    while value <= hi:
        row = dot_y(value) // 4
        if not any(r == row for r, _ in ticks):
            ticks.append((row, value))
        value += step
    return Chart(cells, lo, hi, ticks, dot_y(0.0) // 4 if lo <= 0 <= hi else None)


def money_label(v: float) -> str:
    """An axis label: +$20,000 / -$2,500 / $0 (cents only for steps under $1)."""
    amount = f"{abs(v):,.0f}" if abs(v - round(v)) < 1e-9 else f"{abs(v):,.2f}"
    if abs(v) < 1e-9:
        return "$0"
    return f"{'+' if v > 0 else '-'}${amount}"
