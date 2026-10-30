"""The real game, in a pseudo-terminal: deck-size rules and their messages, no hand lock, a genuine mid-hand
reshuffle on screen, the data written when the game is quit or killed, and the casino floor (python3 -m casino)
-- its menus by keyboard and mouse, the bank options, and blackjack launched from it. Needs `pyte`
(pip install pyte); skipped without it. Takes a few minutes -- it types at human speed so the curses screen
keeps up."""
import importlib.util
import json
import os
import signal
import sqlite3
import sys
import tempfile
import time

missing = [m for m in ("pty", "pyte") if importlib.util.find_spec(m) is None]   # pty is Unix-only; pyte is a pip package
if missing:
    print(f"check_ui: SKIPPED ({missing[0]} not available -- pip install pyte)")
    sys.exit(0)

from ui_support import FORCED_LAUNCHER, LEFT, RIGHT, Game

fails = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def db(home):
    c = sqlite3.connect(os.path.join(home, ".cs-blackjack", "blackjack.db"))
    c.row_factory = sqlite3.Row
    return c


def bank_file(home):
    with open(os.path.join(home, ".baddies-casino", "bank.json")) as fh:
        return json.load(fh)


def quit_game(g):
    g.send("\x1b", 1.3)
    g.command("quit", 1.5)
    return g.wait_exit()


# =============================================================== A. deck-size rules through the UI
home = tempfile.mkdtemp(prefix="csbj-ui-")
g = Game(home)
g.pump(2.5)
check("6 DECK  •  75%" in g.text(), "starts as the default 6-deck, 75% game")

g.command("decks 1")
msg = g.line_with("single-deck limits")
check(msg is not None and "24 cards" in msg and "at most 2 hands" in msg, f"'decks 1' explains the limits: {msg[:120] if msg else None}")
g.command("newshoe", 0.5)
g.send("\r", 3.0)
check("1 DECK  •  54%" in g.text(), "single-deck header shows the real cut depth: 1 DECK • 54%")
g.command("hands 3")
check(g.line_with("Single-deck games are limited to 2 hands") is not None, "'hands 3' is refused on a single deck")

# fund Hand #2 through the grid -> 2 hands; play a round; then go back to 1 hand mid-shoe
g.send("\x1b", 1.3)
g.send(LEFT, 0.4); g.send("10", 0.4); g.send("\r", 0.8)
check(g.wager_row() is not None and g.wager_row()[0] == "10", f"Hand #2 funded through the grid: {g.wager_row()}")
g.send("\r", 4.0)
g.to_idle()
g.command("hands 1")
check(g.line_with("Playing 1 hand(s) per round") is not None and g.line_with("locked") is None,
      "AFTER a round on this shoe, 'hands 1' is accepted (there is no lock any more)")
g.send("\r", 4.0)
g.to_idle()
g.command("hands 2")
check(g.line_with("Playing 2 hand(s) per round") is not None, "...and back to 2 hands, mid-shoe")
g.send("\r", 4.0)
g.to_idle()

# clearing Hand #2's wager through the grid used to be refused while locked; now it's allowed
g.send("\x1b", 1.3)
g.send(LEFT, 0.4); g.send("0", 0.4); g.send("\r", 0.8)
check(g.line_with("locked") is None and g.wager_row() is not None and g.wager_row()[0] == "0", f"clearing Hand #2 through the grid is allowed: {g.wager_row()}")
g.send(RIGHT, 0.4); g.send(RIGHT, 0.4); g.send("10", 0.4); g.send("\r", 0.8)
check(g.line_with("Single-deck games are limited to 2 hands") is not None, "...but funding Hand #3 is still refused")

g.command("gamerules", 1.0)
scr = g.text()
check("SINGLE-DECK LIMITS" in scr and "at least 24 cards left" in scr and "RUNNING OUT OF CARDS" in scr
      and "locked at" not in scr and "until the next shuffle" not in scr and "changeable any time" in scr,
      "gamerules: shows the 24-card minimum and the failsafe note, and no hand-lock text (only the side-bet deck locks remain)")
g.send(" ", 0.6)

g.command("decks 2", 0.5)
g.command("newshoe", 0.5)
g.send("\r", 3.0)
check("2 DECK  •  75%" in g.text(), "two decks at the default deckpen: 2 DECK • 75%")
g.command("deckpen 0.95")
msg = g.line_with("Deck penetration set")
check(msg is not None and "capped at 0.80" in msg, f"'deckpen 0.95' on two decks: {msg}")
g.command("newshoe", 0.5)
g.send("\r", 3.0)
check("2 DECK  •  80%" in g.text(), "...and the header shows the 80% cap")

# three or more decks: the floor scales with the hands in play
g.command("decks 6", 0.5)
g.command("newshoe", 0.5)
g.send("\r", 3.0)
g.command("deckpen 0.99")
msg = g.line_with("Deck penetration set")
check(msg is not None and "fewer than 28 cards" in msg, f"'deckpen 0.99' on six decks with 1 hand names the 28-card floor: {msg}")
g.command("hands 2")
g.command("deckpen 0.99")
msg = g.line_with("Deck penetration set")
check(msg is not None and "fewer than 40 cards" in msg, f"...and with 2 hands, 40: {msg}")
g.command("newshoe", 0.5)
g.send("\r", 3.0)
check("6 DECK  •  87%" in g.text(), "the header shows the depth that actually applies at 2 hands (1 - 40/312 = 87%)")
g.command("gamerules", 1.0)
scr = g.text()
check("MINIMUM CARDS" in scr and "28 / 40 / 52 for 1 / 2 / 3 hands" in scr and "RUNNING OUT OF CARDS" in scr, "gamerules: shows the per-hand floors (28 / 40 / 52) and the failsafe note")
g.send(" ", 0.6)

check(quit_game(g), "clean exit")
c = db(home)
check(c.execute("pragma integrity_check").fetchone()[0] == "ok" and c.execute("pragma user_version").fetchone()[0] == 4, "database intact, schema v4")
rows = c.execute("select card_order, retired_at from shoes").fetchall()
check(all("|" in r[0] and r[1] for r in rows), f"every shoe retired with its '|' marker ({len(rows)} shoes)")
check(c.execute("select count(*) from hands").fetchone()[0] >= 3 and c.execute("select count(*) from hands where reshuffled_mid_round=1").fetchone()[0] == 0,
      "rounds were logged, none flagged as reshuffled (nothing ran out)")
spots = [r[0] for r in c.execute("select count(distinct spot_number) from hands group by round_id")]
check(1 in spots and 2 in spots, f"the rounds alternated between 1 and 2 hands on the same single-deck shoe ({sorted(set(spots))})")
c.close()

# =============================================================== B. a real mid-hand reshuffle on screen
home = tempfile.mkdtemp(prefix="csbj-ui-rs-")
g = Game(home, cmd=[sys.executable, str(FORCED_LAUNCHER)])
g.pump(2.5)
check(g.alive(), "launched with a five-card first shoe")
g.send("\r", 4.0)                                  # deal 2♣ / 9♦ / 3♣ / 8♦
check("SPACE Hit" in g.text(), "the round is in the player's turn")
g.send(" ", 1.5)                                   # hit: takes the spare 4♥ (player 9); the shoe is now empty
check("mid-hand" not in g.text(), "after the first hit the shoe is empty but nothing has happened yet")
os.write(g.fd, b" ")                               # hit again: needs a card that isn't there
seen = None
t_end = time.time() + 8
while time.time() < t_end and seen is None:
    g.pump(0.25)
    seen = g.line_with("mid-hand")
check(seen is not None and "reshuffled" in seen, f"the player is told what happened: {seen}")
check(b"Traceback" not in g.raw and g.alive(), "no crash: the game is still running")
g.send("\r", 3.0)                                  # stand
g.to_idle()
check("[RETURN] to Deal" in g.text(), "the round finished normally and the game is back at the betting screen")
check(quit_game(g), "clean exit")
c = db(home)
flagged = c.execute("select count(*), min(shoe_id) from hands where reshuffled_mid_round=1").fetchone()
mid = c.execute("select shoe_id, cut_reason from shoes where cut_reason='mid_round'").fetchall()
check(flagged[0] >= 1 and len(mid) == 1, f"the database flagged the round ({flagged[0]} hand row(s)) and opened one mid_round shoe (id {mid[0][0] if mid else None})")
check(mid and flagged[1] == mid[0][0] - 1, "...and that round's rows point at the shoe it started on, not the new one")
old = c.execute("select card_order from shoes where shoe_id=?", (flagged[1],)).fetchone()[0]
check(old.endswith("|"), "the exhausted shoe was closed off with its '|' marker and an empty never-dealt tail")
check(c.execute("select count(*) from shoes where retired_at is null").fetchone()[0] == 0, "every shoe is retired after quit")
c.close()

# =============================================================== C. what survives being closed or killed
for label, sig in (("SIGTERM (kill)", signal.SIGTERM), ("SIGHUP (terminal window closed)", signal.SIGHUP)):
    home = tempfile.mkdtemp(prefix="csbj-ui-sig-")
    g = Game(home)
    g.pump(2.5)
    g.send("\r", 4.0)
    g.to_idle()
    g.send("\r", 4.0)                                   # a second round, so cards have been dealt
    g.kill(sig)
    check(g.wait_exit(10), f"{label}: the game exits")
    c = db(home)
    shoe = c.execute("select * from shoes order by shoe_id desc limit 1").fetchone()
    dealt, bar, tail = shoe["card_order"].partition("|")
    check(bool(bar) and len(dealt) == 2 * shoe["cards_dealt"] and len(tail) > 0 and shoe["retired_at"] is not None,
          f"{label}: the shoe is retired with its dealt cards, '|', and the never-dealt tail ({len(dealt) // 2} + {len(tail) // 2} cards)")
    check(len(dealt + tail) == 2 * 312, f"{label}: dealt + never-dealt account for all 312 cards")
    check(c.execute("select count(*) from sessions where ended_at is null").fetchone()[0] == 0, f"{label}: the session was closed")
    check(c.execute("select count(*) from hands").fetchone()[0] >= 1, f"{label}: the rounds played were kept")
    table_pl = c.execute("select sum(total_pl) from hands").fetchone()[0]
    check(abs(bank_file(home)["balance"] - (10_000 + table_pl)) < 1e-6, f"{label}: the casino bank was told about every round ({table_pl:+.2f})")
    c.close()

# =============================================================== D. --db starts from a clean slate
home = tempfile.mkdtemp(prefix="csbj-ui-db-")
fresh = os.path.join(home, "practice.db")
g = Game(home, args=("--db", fresh))
g.pump(2.5)
g.send("\r", 4.0)
g.to_idle()
check(quit_game(g), "--db: clean exit")
check(os.path.exists(fresh) and not os.path.exists(os.path.join(home, ".cs-blackjack", "blackjack.db")), "--db FILE: history goes to that file, and the default database was not created")
c = sqlite3.connect(fresh)
check(c.execute("select count(*) from hands").fetchone()[0] >= 1, "...and it holds the rounds played")
c.close()

# =============================================================== E. the casino floor
DOWN = "\x1bOB"


def click(g, y, x):
    """A left click at a screen cell: an X10 mouse report (the encoding this terminal type's ncurses reads),
    press then release."""
    g.send(b"\x1b[M" + bytes([32, 33 + x, 33 + y]), 0.15)
    g.send(b"\x1b[M" + bytes([35, 33 + x, 33 + y]), 0.6)


def find(g, text):
    for y, line in enumerate(g.text().splitlines()):
        if text in line:
            return y, line.index(text)
    return None


lit = lambda g: (g.line_with("▶") or "")
home = tempfile.mkdtemp(prefix="csbj-ui-floor-")
g = Game(home, rows=60, cols=238, cmd=[sys.executable, "-m", "casino"])
g.pump(2.5)
screen = g.text()
lines = g.screen.display
check(screen.count("█") > 500 and "GAMES" in screen and "BANK" in screen and "Balance: $10,000.00" in screen,
      "the casino floor: the block-letter sign, the GAMES and BANK menus, and a new player's $10,000.00")
check(lit(g).startswith("▶ Classic Blackjack") and "Leave Casino" in screen, "Classic Blackjack starts highlighted")
sign_y, sign_x = find(g, "█")
check(lines[0].strip() == "" and sign_y == 1 and g.screen.buffer[sign_y][sign_x].fg == "87ff00" and "▀" in lines[8] and lines[9].strip() == "",
      "the sign starts a row from the top, in lime green, on one line (8 rows)")
check(sign_x >= 4 and max(i for i, ch in enumerate(lines[1]) if ch == "█") <= 238 - 5, "...with room on either side")
banner_y, _ = find(g, "Luxury Gaming and Amenities")
purple = [x for x in range(238) if g.screen.buffer[banner_y][x].bg == "8700af"]
check(lines[banner_y - 1].strip() == "" and purple and (purple[0], purple[-1]) == (63, 174),
      f"a blank row, then the purple banner, 3 inches (63 columns) clear on either side: {purple[:1]}..{purple[-1:]}")
games_y, games_x = find(g, "┌─ GAMES")
right_edge = max(x for x, ch in enumerate(lines[games_y]) if ch == "┐")
check(games_y == banner_y + 2 and games_x == 21 and right_edge == 238 - 21 - 1, "the menus run from 1 inch (21 columns) in from each side")
check(not any(ch in line for line in lines[51:] for ch in "┌┐└┘│"), "the bottom 15% of the screen (the last 9 rows) holds no tables")
check(lines[-1].strip().startswith("Intellectual Property of Dylan Behseresht, 2026.") and lines[-1].strip().endswith("expressly prohibited"),
      "the intellectual-property notice is on the bottom line")

g.send("\r", 3.5)
check("Bankroll: $10,000.00" in g.text(), "Enter on Classic Blackjack launches the game, playing from the bank's balance")
g.send("\r", 4.0)
g.to_idle()
g.send("\x1b", 1.3)
g.command("exit", 3.0)
c = db(home)
table_pl = c.execute("select sum(total_pl) from hands").fetchone()[0]
c.close()
bank = bank_file(home)
check("Back on the floor from Classic Blackjack." in g.text() and g.alive(), "'exit' in blackjack comes back to the floor")
check(abs(bank["game_winnings"]["blackjack"] - table_pl) < 1e-6 and f"Balance: ${bank['balance']:,.2f}" in g.text(),
      f"...where the balance shows what was won or lost at the table ({table_pl:+.2f}), as the bank file has it")

g.send(RIGHT, 0.4)
check(lit(g).endswith("▶ Account Summary"), "Right moves the highlight into the BANK menu")
g.send("\r", 0.8)
check("ACCOUNT SUMMARY" in g.text() and g.line_with("Blackjack") is not None, "Account Summary opens, listing blackjack's winnings")
g.send("x", 0.6)
g.send(DOWN, 0.4)
g.send("\r", 0.6)
g.send("1,000", 0.4)
g.send("\r", 0.8)
check("Deposited $1,000.00" in g.text() and abs(bank_file(home)["deposited"] - 11_000) < 1e-9, "Deposit takes an amount and puts it in the bank")

at = find(g, "Withdraw")
click(g, *at)
check(lit(g).endswith("▶ Withdraw"), "a click highlights an option")
click(g, 1, 1)
check(lit(g) == "", "a click off the menus clears the highlight")
click(g, *at)
click(g, *at)
check("WITHDRAW" in g.text() and "Amount:" in g.text(), "a second click on the highlighted option picks it")
g.send("999999", 0.3)
g.send("\r", 0.6)
check(g.line_with("You can withdraw at most") is not None, "a withdrawal over the balance is refused, with the most you can take")
for _ in range(6):
    g.send("\x7f", 0.1)
g.send("400", 0.3)
g.send("\r", 0.8)
check("Withdrew $400.00" in g.text() and abs(bank_file(home)["withdrawn"] - 400) < 1e-9, "...and an amount within it comes out")

g.send(DOWN, 0.4)
g.send("\r", 0.8)
rows = g.text()
listing = rows[rows.index("TRANSACTIONS"):] if "TRANSACTIONS" in rows else ""
check(listing and listing.index("Withdrawal") < listing.index("Deposit") < listing.index("Opening"), "Transactions lists them, newest first")
g.send("q", 0.6)
check("TRANSACTIONS" not in g.text(), "q closes the list")
g.send(LEFT, 0.4)
g.send("\r", 3.5)
check("Bankroll: $" in g.text(), "back into Classic Blackjack")
g.command("quit", 3.0)
check(g.wait_exit() and os.WEXITSTATUS(g.exit_status) == 0, "'quit' in a game closes Baddie's Casino entirely, cleanly")

# =============================================================== F. 'exit' from blackjack started on its own
home = tempfile.mkdtemp(prefix="csbj-ui-exit-")
practice = os.path.join(home, "practice.db")
g = Game(home, rows=60, cols=238, args=("--db", practice))
g.pump(2.5)
g.send("\r", 4.0)
g.to_idle()
g.command("exit", 3.0)
check("Luxury Gaming and Amenities" in g.text() and g.alive(), "'exit' from blackjack started on its own (python3 -m blackjack) opens the casino floor")
g.send("\r", 3.5)
g.send("\r", 4.0)
g.to_idle()
g.command("exit", 3.0)
check("Back on the floor from Classic Blackjack." in g.text(), "...and blackjack picked there comes back to it on 'exit' too")
g.send("q", 1.0)
check(g.wait_exit() and os.WEXITSTATUS(g.exit_status) == 0, "q on the floor closes the casino")
c = sqlite3.connect(practice)
sessions = c.execute("select count(*) from sessions where ended_at is not null").fetchone()[0]
c.close()
check(sessions == 2 and not os.path.exists(os.path.join(home, ".cs-blackjack", "blackjack.db")),
      "both visits played on the --db file (2 closed sessions there), never the default database")

print()
print("check_ui: FAILED" if fails else "check_ui: ALL UI CHECKS PASSED", *fails, sep="\n  - " if fails else "")
sys.exit(1 if fails else 0)
