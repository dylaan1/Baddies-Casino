"""The casino bank: the one bankroll every game plays from, kept in its own file
(~/.baddies-casino/bank.json) rather than with any one game's save.

The balance is always exactly what's been deposited, minus what's been
withdrawn, plus what the games have won (a negative figure for a game that's
down):

    balance = deposited - withdrawn + sum(game_winnings.values())

so the file says both how much is there and where it came from. Deposits and
withdrawals -- money the player moves in or out themselves -- are also listed
one by one in `transactions`; a game's winnings are kept as one running total
per game (a line per hand would bury the deposits).

Every change is written straight away, atomically (a temp file renamed into
place), under a lock -- and each one re-reads the file first and applies just
its own change, so two programs sharing the bank (the same game open in two
terminals, say) never undo each other's updates. A change that couldn't be
written (a full disk) is held, in order, and goes in with the next write that
works. A file that can't be read is renamed aside, never overwritten, and the
bank starts over from a fresh opening deposit, with a warning to say so.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no flock; each write is still atomic
    fcntl = None

CASINO_DIR = Path.home() / ".baddies-casino"
BANK_PATH = CASINO_DIR / "bank.json"
BANK_SCHEMA_VERSION = 1
DEFAULT_OPENING_DEPOSIT = 10_000.0

_READ_ERRORS = (ValueError, TypeError, KeyError, AttributeError, OSError)


@dataclass
class Opening:
    """What a brand-new bank starts out holding: the money put in (or, when
    negative, taken out) to open it, and anything already won at the games --
    for a player whose bankroll a game used to keep itself (see
    blackjack/bank.py). A new player just gets the default opening deposit."""

    deposit: float = DEFAULT_OPENING_DEPOSIT
    game_winnings: Dict[str, float] = field(default_factory=dict)
    note: str = "Opening deposit"

    @classmethod
    def carried_over(cls, balance: float, game_winnings: Dict[str, float], note: str) -> "Opening":
        """An opening that lands on `balance` exactly: whatever of it the games
        didn't win counts as deposited (or, if they won more than the balance,
        the difference as withdrawn)."""
        return cls(deposit=balance - sum(game_winnings.values()), game_winnings=dict(game_winnings), note=note)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Bank:
    def __init__(self, path: Path = BANK_PATH):
        self.path = path
        self.deposited = 0.0
        self.withdrawn = 0.0
        self.game_winnings: Dict[str, float] = {}
        # Deposits and withdrawals in the order they happened, oldest first:
        # {"at", "kind" ("opening" | "deposit" | "withdrawal"), "amount"
        # (signed: + in, - out), "balance" (after it), "note"}.
        self.transactions: List[Dict] = []
        self.error: Optional[str] = None  # the most recent failed write, if any
        # Changes made but not yet written (a write failed), oldest first:
        # applied again, after re-reading the file, by the next write.
        self._unsaved: List[Callable[[], None]] = []
        self.warning: Optional[str] = None  # a one-time note from open(): a corrupt file set aside

    # ---- figures ----

    @property
    def balance(self) -> float:
        return self.deposited - self.withdrawn + self.total_winnings

    @property
    def total_winnings(self) -> float:
        return sum(self.game_winnings.values())

    @property
    def on_disk(self) -> bool:
        """True once the bank's file exists and the last write to it worked."""
        return self.error is None and self.path.exists()

    # ---- opening ----

    @classmethod
    def open(cls, path: Optional[Path] = None, opening: Optional[Callable[[], Opening]] = None) -> "Bank":
        """Load the bank, or create it the first time: `opening()` says what
        it starts with (called only then -- it may be slow), else the default
        opening deposit. Never raises; a failed write is left in .error."""
        bank = cls(path or BANK_PATH)
        with bank._locked():
            if bank.path.exists() and bank._read_or_set_aside():
                return bank
            start = opening() if opening is not None else Opening()
            bank._apply_opening(start)
            bank._write()
        return bank

    def _apply_opening(self, start: Opening) -> None:
        self.deposited = max(start.deposit, 0.0)
        self.withdrawn = max(-start.deposit, 0.0)
        self.game_winnings = {game: float(won) for game, won in start.game_winnings.items()}
        self.transactions = [
            {"at": _now(), "kind": "opening", "amount": start.deposit, "balance": self.balance, "note": start.note}
        ]

    # ---- changes ----

    def deposit(self, amount: float, note: str = "Deposit") -> bool:
        return self.transfer(abs(amount), note)

    def withdraw(self, amount: float, note: str = "Withdrawal") -> bool:
        return self.transfer(-abs(amount), note)

    def transfer(self, amount: float, note: str) -> bool:
        """Money the player moves in (amount > 0) or out (< 0) themselves.
        Returns False if it couldn't be written (it still counts in memory)."""
        if not amount:
            return True
        at = _now()

        def change() -> None:
            if amount > 0:
                self.deposited += amount
            else:
                self.withdrawn -= amount
            kind = "deposit" if amount > 0 else "withdrawal"
            self.transactions.append({"at": at, "kind": kind, "amount": amount, "balance": self.balance, "note": note})

        return self._update(change)

    def record_winnings(self, game: str, amount: float) -> bool:
        """Add what a game won (amount > 0) or lost (< 0) to its running total."""
        if not amount:
            return True

        def change() -> None:
            self.game_winnings[game] = self.game_winnings.get(game, 0.0) + amount

        return self._update(change)

    def _update(self, change: Callable[[], None]) -> bool:
        with self._locked():
            if self.path.exists() and self._read_or_set_aside():
                # The file now has anyone else's changes -- but none of this
                # bank's unwritten ones, so those go on again first.
                for earlier in self._unsaved:
                    earlier()
            change()
            if self._write():
                self._unsaved.clear()
                return True
            self._unsaved.append(change)
            return False

    # ---- the file ----

    def to_dict(self) -> dict:
        return {
            "schema_version": BANK_SCHEMA_VERSION,
            "balance": self.balance,  # for reading the file by eye -- always recomputed from the figures below
            "deposited": self.deposited,
            "withdrawn": self.withdrawn,
            "game_winnings": dict(self.game_winnings),
            "transactions": list(self.transactions),
        }

    def _read(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf8"))
        deposited, withdrawn = float(data["deposited"]), float(data["withdrawn"])
        winnings = {str(game): float(won) for game, won in data["game_winnings"].items()}
        transactions = [dict(t) for t in data.get("transactions", [])]
        self.deposited, self.withdrawn, self.game_winnings, self.transactions = deposited, withdrawn, winnings, transactions

    def _read_or_set_aside(self) -> bool:
        """Read the file into this bank; if it can't be read, rename it aside
        (it's never overwritten) and return False."""
        try:
            self._read()
            return True
        except _READ_ERRORS:
            aside = self.path.with_name(f"{self.path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
            try:
                os.replace(self.path, aside)
                self.warning = f"Bank file was unreadable -- set aside as {aside.name}."
            except OSError:
                self.warning = "Bank file was unreadable."
            return False

    def _write(self) -> bool:
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf8") as fh:
                fh.write(json.dumps(self.to_dict(), indent=2))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                tmp.unlink()
            self.error = f"{type(exc).__name__}: {exc}"
            return False
        self.error = None
        return True

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold the bank's lock file for one read-change-write. If the lock
        can't be taken (no flock, or the folder can't be created), carry on
        without it -- the write itself is still atomic."""
        fh = None
        try:
            if fcntl is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fh = open(self.path.with_name(self.path.name + ".lock"), "a")
                fcntl.flock(fh, fcntl.LOCK_EX)
        except OSError:
            if fh is not None:
                fh.close()
            fh = None
        try:
            yield
        finally:
            if fh is not None:
                fh.close()  # closing releases the lock
