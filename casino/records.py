"""What a game hands the casino floor's DATA menu about its own history: one
record per session it's played, its P/L round by round, and -- a game with
dealers -- its results dealer by dealer. Each game reads its own history
(blackjack/records.py) and returns these; the floor only shows them
(casino/data_views.py)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


class RecordsError(Exception):
    """A game's history couldn't be read -- the message says why."""


@dataclass
class SessionRecord:
    number: int  # the game's own id for the session
    started_at: str  # UTC, ISO 8601
    ended_at: Optional[str]  # None while it's still going
    rounds: int
    hands: int
    won: int
    lost: int
    pushed: int
    wagered: float  # on main bets
    main_pl: float
    side_pl: float  # side bets (and insurance)
    # Game-specific figures for the session's detail view, in order: (label, value).
    details: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def total_pl(self) -> float:
        return self.main_pl + self.side_pl

    @property
    def ev(self) -> Optional[float]:
        """Realized edge on main bets, in percent (None before any were made)."""
        return self.main_pl / self.wagered * 100 if self.wagered > 0 else None


@dataclass
class DealerRecord:
    name: str
    sessions: int  # sessions they dealt in
    rounds: int
    hands: int
    won: int
    lost: int
    pushed: int
    wagered: float  # on main bets
    main_pl: float
    side_pl: float  # side bets (and insurance)

    @property
    def total_pl(self) -> float:
        return self.main_pl + self.side_pl

    @property
    def ev(self) -> Optional[float]:
        """Realized edge on main bets, in percent (None before any were made)."""
        return self.main_pl / self.wagered * 100 if self.wagered > 0 else None


@dataclass
class DealerTable:
    dealers: List[DealerRecord] = field(default_factory=list)  # best total P/L first
    # Play from before the game recorded its dealers: part of its lifetime
    # P/L, but no one's to put it against.
    unrecorded_hands: int = 0
    unrecorded_pl: float = 0.0


@dataclass
class PLHistory:
    # (when the round was played, UTC ISO 8601; the running P/L after it),
    # oldest first, starting from $0 at the first round recorded.
    rounds: List[Tuple[str, float]] = field(default_factory=list)
    # P/L from play with no round-by-round record (an older version's
    # lifetime totals): part of the game's lifetime P/L, but not chartable.
    unrecorded: float = 0.0


def money(x: float) -> str:
    """$1,234.50, or -$1,234.50."""
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def signed(x: float) -> str:
    """+$1,234.50, or -$1,234.50."""
    return f"-${-x:,.2f}" if x < 0 else f"+${x:,.2f}"
