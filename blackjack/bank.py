"""Blackjack's link to the casino bank (casino/bank.py), which holds the
bankroll every game in Baddie's Casino plays from.

Blackjack used to keep the bankroll in its own state file. The first time the
bank is opened -- by blackjack, or by anything else opening it with this
module's `opening` -- that bankroll moves into it: what blackjack has won over its lifetime (the history database's
lifetime P/L, imported pre-database play included) as blackjack's winnings,
and the rest as deposited. A brand-new player gets the bank's default opening
deposit instead.
"""
from __future__ import annotations

from typing import Optional

from casino.bank import Bank, Opening

from . import persist
from .engine import BANK_GAME_KEY
from .history import HistoryDB


def opening(history: Optional[HistoryDB] = None) -> Opening:
    """What a brand-new bank should start with, from what blackjack kept
    before the bank existed. `history` is the game's own open database;
    without one, the default database is opened just to read the lifetime
    P/L."""
    legacy = persist.pending_legacy_bankroll()
    if legacy is None:
        legacy = persist.read_legacy_bankroll(persist.STATE_PATH)
    if legacy is None:
        return Opening()
    db = history if history is not None else HistoryDB.open()
    try:
        if history is None:
            # The same one-time import the game makes on launch, so the
            # lifetime P/L includes play an older version counted itself.
            persist.set_legacy_stats(persist.read_legacy_stats(persist.STATE_PATH))
            db.import_pending_legacy_stats()
        stats = db.load_stats()
    finally:
        if history is None and db.conn is not None:
            db.conn.close()
    won = stats.total_lifetime_pl() if stats is not None else 0.0
    return Opening.carried_over(legacy, {BANK_GAME_KEY: won}, "Bankroll carried over from Blackjack's save file")


def open_bank(history: Optional[HistoryDB] = None) -> Bank:
    """Open the casino bank for a blackjack session (creating it from
    blackjack's old bankroll the first time). Once the bank's own file holds
    the bankroll, the state file stops carrying its old copy."""
    bank = Bank.open(opening=lambda: opening(history))
    if bank.on_disk:
        persist.clear_legacy_bankroll()
    return bank
