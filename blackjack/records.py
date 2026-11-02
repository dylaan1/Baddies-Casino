"""Blackjack's history for the casino floor's DATA menu (casino/records.py):
every session it has logged, its P/L round by round, and its results dealer
by dealer -- read straight from the history database, read-only, so a game
open in another terminal carries on undisturbed and nothing here can change
what's recorded."""
from __future__ import annotations

import sqlite3
import textwrap
from contextlib import closing
from pathlib import Path
from typing import List, Optional

from casino.records import DealerRecord, DealerTable, PLHistory, RecordsError, SessionRecord, money, signed

from . import history

_END_REASONS = {
    "quit": "quit (or exit)",
    "newsession": "newsession",
    "restore": "a restore",
    "abandoned": "the game closing unexpectedly",
    "hardreset": "hardreset (an older version)",
}


def _connect(db_path: Optional[Path]) -> Optional[sqlite3.Connection]:
    """The history database, opened read-only -- or None if blackjack has
    never been played (there's no database yet)."""
    path = db_path or history.DB_PATH
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(history._readonly_uri(path), uri=True, timeout=2.0)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.Error as exc:
        raise RecordsError(f"Blackjack's history couldn't be read ({exc}).")
    if version != history.SCHEMA_VERSION:
        conn.close()
        if version > history.SCHEMA_VERSION:
            raise RecordsError("Blackjack's history was written by a newer version of the game.")
        raise RecordsError("Open Classic Blackjack once to bring its history up to date.")
    conn.row_factory = sqlite3.Row
    return conn


DEALT_BY_WIDTH = 36  # names per line in the session detail before it wraps


def _dealt_by(conn: sqlite3.Connection, sid: int) -> list:
    """("Dealt by", names) -- every dealer who dealt in the session, in the
    order they first did, wrapped onto more lines when there are many."""
    names = [r[0] for r in conn.execute(
        "SELECT dealer_name FROM hands WHERE session_id = ? AND dealer_name IS NOT NULL"
        " GROUP BY dealer_name ORDER BY MIN(hand_id)", (sid,))]
    if not names:
        return [("Dealt by", "not recorded (before the dealers)")]
    lines = textwrap.wrap(", ".join(names), DEALT_BY_WIDTH, break_long_words=False)
    return [("Dealt by" if i == 0 else "", line) for i, line in enumerate(lines)]


def _details(conn: sqlite3.Connection, row: sqlite3.Row) -> list:
    sid = row["session_id"]
    best, worst = conn.execute(
        "SELECT MAX(main_pl), MIN(main_pl) FROM hands WHERE outcome <> 'abandoned' AND session_id = ?", (sid,)
    ).fetchone()
    return _dealt_by(conn, sid) + [
        ("Surrendered", f"{row['hands_surrendered']}"),
        ("Doubles", f"{row['doubles']}"),
        ("Splits", f"{row['splits']}  (aces {row['aces_split']}, tens {row['tens_split']})"),
        ("Your blackjacks", f"{row['player_blackjacks']}"),
        ("Dealer blackjacks", f"{row['dealer_blackjacks']}"),
        ("Dealer 21s", f"{row['dealer_21s']}"),
        ("Dealer busts", f"{row['dealer_busts']}"),
        (
            "Longest streaks",
            f"W{row['longest_win_streak']}  L{row['longest_loss_streak']}  P{row['longest_push_streak']}",
        ),
        ("Shoes played", f"{row['shoes_played']:g}"),
        ("Max drawdown", money(history.lowest_running_pl(conn, "WHERE session_id = ?", (sid,)))),
        ("Biggest hand win", signed(max(best or 0.0, 0.0))),
        ("Biggest hand loss", signed(min(worst or 0.0, 0.0))),
        ("Ended by", _END_REASONS.get(row["end_reason"], "still playing" if row["ended_at"] is None else str(row["end_reason"]))),
    ]


def sessions(db_path: Optional[Path] = None) -> List[SessionRecord]:
    """Every session with a hand in it, newest first."""
    conn = _connect(db_path)
    if conn is None:
        return []
    with closing(conn):
        try:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE session_id IN (SELECT session_id FROM hands) ORDER BY session_id DESC"
            ).fetchall()
            return [
                SessionRecord(
                    number=r["session_id"],
                    started_at=r["started_at"],
                    ended_at=r["ended_at"],
                    rounds=r["rounds_played"],
                    hands=r["hands_played"],
                    won=r["hands_won"],
                    lost=r["hands_lost"],
                    pushed=r["hands_pushed"],
                    wagered=r["main_wagered"],
                    main_pl=r["main_pl"],
                    side_pl=r["sidebet_pl"],
                    details=_details(conn, r),
                )
                for r in rows
            ]
        except sqlite3.Error as exc:
            raise RecordsError(f"Blackjack's history couldn't be read ({exc}).")


def dealers(db_path: Optional[Path] = None) -> DealerTable:
    """Every dealer's results, best total P/L first -- counted the way the
    sessions are: hands and W-L-P from settled hands, rounds only those that
    finished, wagers and P/L from every hand -- so a session's dealers add up
    to the session. Plus the play from before dealers were recorded."""
    conn = _connect(db_path)
    if conn is None:
        return DealerTable()
    with closing(conn):
        try:
            rows = conn.execute(
                """SELECT dealer_name, COUNT(DISTINCT session_id),
                          COUNT(DISTINCT round_id) - COUNT(DISTINCT CASE WHEN outcome = 'abandoned' THEN round_id END),
                          SUM(outcome <> 'abandoned'), SUM(outcome = 'win'), SUM(outcome = 'loss'), SUM(outcome = 'push'),
                          SUM(final_bet), SUM(main_pl), SUM(sidebet_pl)
                   FROM hands WHERE dealer_name IS NOT NULL GROUP BY dealer_name"""
            ).fetchall()
            unrecorded_hands, unrecorded_pl = conn.execute(
                "SELECT COALESCE(SUM(outcome <> 'abandoned'), 0), COALESCE(SUM(total_pl), 0) FROM hands WHERE dealer_name IS NULL"
            ).fetchone()
        except sqlite3.Error as exc:
            raise RecordsError(f"Blackjack's history couldn't be read ({exc}).")
    records = [DealerRecord(name, *(int(v) for v in counts), float(wagered), float(main), float(side))
               for name, *counts, wagered, main, side in (tuple(r) for r in rows)]
    records.sort(key=lambda d: (-round(d.total_pl, 2), d.name.casefold()))
    return DealerTable(records, int(unrecorded_hands), float(unrecorded_pl))


def pl_history(db_path: Optional[Path] = None) -> PLHistory:
    """The running P/L (main bets and side bets) after every round recorded,
    from $0 at the first, plus the lifetime P/L an older version counted
    before rounds were recorded one by one."""
    conn = _connect(db_path)
    if conn is None:
        return PLHistory()
    with closing(conn):
        try:
            points, running = [], 0.0
            for played_at, round_pl in conn.execute(
                "SELECT MIN(played_at), SUM(total_pl) FROM hands GROUP BY round_id ORDER BY MIN(hand_id)"
            ):
                running += round_pl
                points.append((played_at, running))
            unrecorded = conn.execute(
                "SELECT COALESCE(SUM(stat_value), 0) FROM imported_stats"
                " WHERE stat_key IN ('lifetime_main_pl', 'lifetime_sidebet_pl')"
            ).fetchone()[0]
        except sqlite3.Error as exc:
            raise RecordsError(f"Blackjack's history couldn't be read ({exc}).")
    return PLHistory(points, float(unrecorded))
