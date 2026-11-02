"""Blackjack's history for the casino floor's DATA menu (casino/records.py):
every session it has logged, and its P/L round by round -- read straight
from the history database, read-only, so a game open in another terminal
carries on undisturbed and nothing here can change what's recorded."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import List, Optional

from casino.records import PLHistory, RecordsError, SessionRecord, money, signed

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


def _details(conn: sqlite3.Connection, row: sqlite3.Row) -> list:
    sid = row["session_id"]
    best, worst = conn.execute(
        "SELECT MAX(main_pl), MIN(main_pl) FROM hands WHERE outcome <> 'abandoned' AND session_id = ?", (sid,)
    ).fetchone()
    return [
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
