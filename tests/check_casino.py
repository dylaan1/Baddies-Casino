"""The casino bank (casino/bank.py) and the casino floor's menus (casino/floor.py), apart from the screen.

The bank: its balance is always deposits - withdrawals + game winnings; every change is on disk at once and
never undoes another program's; a change that couldn't be written goes in with the next write; a corrupt file
is set aside, never overwritten. Blackjack's old bankroll moves in exactly once, split into what was deposited
and what blackjack won, and is never lost if the bank can't be created; blackjack's bank commands land as
deposits/withdrawals and its table results as winnings. The floor: where everything goes (the sign, the
banner, the menus' inch margins, the clear bottom 15%, the notice on the last line), menus stop at their ends and
scroll, focus moves between them, clicking off clears the highlight, the bank options move money within the
limits, and a game's 'exit' comes back to the floor while 'quit' closes the casino. The marquee: lights every third
outer cell, alternating green and red with no seam, moving one cell clockwise a step. DATA: blackjack's sessions and
round-by-round P/L read back exactly (and read-only), and the line chart drawn from them."""
import importlib
import io
import json
import math
import os
import sqlite3
import random
from pathlib import Path

from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()
bank_m = S.casino_bank
floor_m = importlib.import_module("casino.floor")
curses = floor_m.curses
BANK = bank_m.BANK_PATH


def on_disk():
    return json.loads(BANK.read_text())


def play(s, n, seed):
    rng = random.Random(seed)
    for _ in range(n):
        s.wagers[0] = 10
        r, err = S.play_round(s, rng, "basic")
        assert r, err
        s.history.record_round(s, r)
        S.ui.save_game(s)
        s.ensure_shoe_ready()


def launch():
    """What the game does on launch (ui._main): state, history, then the bank."""
    rules, wagers, sbw = persist.load_state()
    hist = history.HistoryDB.open()
    hist.import_pending_legacy_stats()
    return S.game_session(rules, wagers, sbw, hist), hist


# =============================================================== A. a brand-new bank
S.reset_data()
b = bank_m.Bank.open()
check(abs(b.balance - bank_m.DEFAULT_OPENING_DEPOSIT) < 1e-9 and b.deposited == bank_m.DEFAULT_OPENING_DEPOSIT and b.game_winnings == {},
      f"a new player's bank opens with the default deposit: {b.balance}")
check(BANK.exists() and on_disk()["schema_version"] == 1 and b.transactions[0]["kind"] == "opening", "...written to ~/.baddies-casino/bank.json, opening entry first")

# =============================================================== B. changes, and the one rule the balance follows
b.deposit(500, "test")
b.withdraw(200, "test")
b.record_winnings("blackjack", 75.5)
b.record_winnings("blackjack", -20)
b.deposit(0, "nothing")
again = bank_m.Bank.open()
check(abs(again.balance - (10_000 + 500 - 200 + 55.5)) < 1e-9 and again.game_winnings == {"blackjack": 55.5},
      f"balance = deposited - withdrawn + winnings, read back from disk: {again.balance}")
check([t["kind"] for t in again.transactions] == ["opening", "deposit", "withdrawal"],
      "deposits and withdrawals are listed one by one; winnings are a running total, and a $0 deposit isn't a transaction")
check(again.transactions[-1]["amount"] == -200 and abs(again.transactions[-1]["balance"] - 10_300) < 1e-9,
      "a withdrawal is stored as a negative amount, with the balance after it")
data = on_disk()
data["balance"] = 1.0
BANK.write_text(json.dumps(data))
check(abs(bank_m.Bank.open().balance - 10_355.5) < 1e-9, "the file's 'balance' is for reading by eye: the bank always recomputes it")

# =============================================================== C. two programs sharing the bank
one, two = bank_m.Bank.open(), bank_m.Bank.open()
one.deposit(100, "terminal 1")
two.record_winnings("blackjack", 10)
both = bank_m.Bank.open()
check(abs(both.balance - (10_355.5 + 110)) < 1e-9 and both.transactions[-1]["note"] == "terminal 1",
      "two programs' changes both land -- each re-reads the file before writing, so neither undoes the other")

# =============================================================== D. a failed write, and a corrupt file
before = BANK.read_text()
real_replace = os.replace
os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
try:
    ok = both.deposit(40, "while the disk was full")
finally:
    os.replace = real_replace
check(ok is False and both.error and not both.on_disk and BANK.read_text() == before,
      f"a write that fails says so and leaves the file as it was: {both.error}")
check(abs(both.balance - 10_505.5) < 1e-9, "...while the change still counts in memory")
both.deposit(1, "disk is back")
check([t["note"] for t in on_disk()["transactions"]][-2:] == ["while the disk was full", "disk is back"] and abs(bank_m.Bank.open().balance - 10_506.5) < 1e-9,
      "...and goes in, in order, with the next write that works")

BANK.write_text('{"deposited": 5, ')
fresh = bank_m.Bank.open()
aside = list(BANK.parent.glob("bank.json.corrupt-*"))
check(fresh.warning and "set aside" in fresh.warning and len(aside) == 1 and aside[0].read_text() == '{"deposited": 5, ',
      f"an unreadable bank file is set aside byte for byte, with a warning: {fresh.warning}")
check(abs(fresh.balance - bank_m.DEFAULT_OPENING_DEPOSIT) < 1e-9 and on_disk()["deposited"] == bank_m.DEFAULT_OPENING_DEPOSIT,
      "...and the bank starts over from a fresh opening deposit")

# =============================================================== E. blackjack's old bankroll moves in, once
# an older version's play: rounds logged to the database, the bankroll kept in the state file, no bank yet
S.reset_data()
rules, wagers, sbw = persist.load_state()
hist = history.HistoryDB.open()
old = engine.GameSession(10_000.0, rules, wagers, sbw, history=hist)
old.ensure_shoe_ready()
rng = random.Random(4)
for _ in range(60):
    old.wagers[0] = 25
    r, _ = S.play_round(old, rng, "basic")
    hist.record_round(old, r)
    old.ensure_shoe_ready()
hist.close(old)
table_pl = history.HistoryDB.open().load_stats().total_lifetime_pl()
persist.STATE_PATH.write_text(json.dumps({"schema_version": 3, "bankroll": old.bankroll, "rules": rules.to_dict()}))
check(not BANK.exists(), f"(an older player: bankroll {old.bankroll:,.2f} in the state file, lifetime P/L {table_pl:+,.2f}, no bank)")

s, hist = launch()
b = s.bank
check(abs(b.balance - old.bankroll) < 1e-9 and abs(s.bankroll - old.bankroll) < 1e-9, "the first launch carries the bankroll into the bank exactly")
check(abs(b.game_winnings["blackjack"] - table_pl) < 1e-9 and abs(b.deposited - 10_000) < 1e-9 and b.withdrawn == 0,
      f"...split into what blackjack won ({b.game_winnings['blackjack']:+,.2f}) and what was deposited ({b.deposited:,.2f})")
check(b.transactions[0]["kind"] == "opening" and "Blackjack" in b.transactions[0]["note"], f"...noted as an opening entry: {b.transactions[0]['note']}")
S.ui.save_game(s)
check("bankroll" not in json.loads(persist.STATE_PATH.read_text()), "once the bank holds it, the state file stops carrying a bankroll")
hist.close(s)
data = json.loads(persist.STATE_PATH.read_text())
persist.STATE_PATH.write_text(json.dumps({**data, "bankroll": 1.0}))   # a stale copy, e.g. from an old backup
s, hist = launch()
check(abs(s.bankroll - old.bankroll) < 1e-9, "with a bank already open, a bankroll left in the state file is never read back in")
hist.close(s)

S.reset_data()
persist.STATE_PATH.write_text(json.dumps({"bankroll": 500.0, "rules": {}, "stats": {"hands_lifetime": 50, "lifetime_main_pl": 2000.0}}))
s, hist = launch()
check(abs(s.bank.balance - 500) < 1e-9 and s.bank.deposited == 0 and abs(s.bank.withdrawn - 1500) < 1e-9,
      "won more than the bankroll holds (it was reset down)? the difference shows as withdrawn, and the balance is still exact")
hist.close(s)

S.reset_data()
persist.STATE_PATH.write_text(json.dumps({"bankroll": 777.0, "rules": {}, "stats": {"hands_lifetime": 5, "lifetime_main_pl": 77.0}}))
b = bank_m.Bank.open(opening=S.bjbank.opening)                          # the casino floor, before blackjack has run
check(abs(b.balance - 777) < 1e-9 and abs(b.game_winnings["blackjack"] - 77) < 1e-9, "the casino floor, opened first, carries the bankroll over the same way")
s, hist = launch()
check(abs(s.bankroll - 777) < 1e-9 and len(s.bank.transactions) == 1, "...and blackjack then uses that bank as it is")
hist.close(s)

# =============================================================== F. the bankroll is never lost if the bank can't be made
S.reset_data()
persist.STATE_PATH.write_text(json.dumps({"bankroll": 4321.0, "rules": {}}))
bank_m.CASINO_DIR.write_text("in the way")                             # the bank's folder can't be created
s, hist = launch()
check(not s.bank.on_disk and s.bank.error and abs(s.bankroll - 4321) < 1e-9, f"a bank that can't be written still plays: {s.bank.error}")
play(s, 5, seed=8)
check(abs(json.loads(persist.STATE_PATH.read_text())["bankroll"] - s.bankroll) < 1e-9,
      "...and meanwhile the state file keeps carrying the bankroll -- the current one")
hist.close(s)
bank_m.CASINO_DIR.unlink()
carried = json.loads(persist.STATE_PATH.read_text())["bankroll"]
s, hist = launch()
check(abs(s.bank.balance - carried) < 1e-9 and BANK.exists(), "the next launch that can write the bank opens it from there")
hist.close(s)

# =============================================================== G. blackjack's own bank commands and its results
S.reset_data()
s, hist = launch()
play(s, 30, seed=11)
cmd = lambda text: commands.handle_command(text, s)
cmd("bank add 250")
cmd("bank 5000")
s.reset_bankroll()
play(s, 10, seed=12)
b = bank_m.Bank.open()
won = hist.conn.execute("select sum(total_pl) from hands").fetchone()[0]
check(abs(b.balance - s.bankroll) < 1e-6, f"the bank's balance is the table's bankroll: {b.balance:,.2f}")
check(abs(b.game_winnings["blackjack"] - won) < 1e-6, f"blackjack's winnings in the bank are exactly the table's P/L ({won:+,.2f}) -- no deposit among them")
notes = [t["note"] for t in b.transactions[1:]]
check(notes == ["Blackjack: bank add", "Blackjack: bank 5000", "Blackjack: bank reset"], f"each bank command is its own deposit/withdrawal: {notes}")
check(abs(b.transactions[2]["balance"] - 5000) < 1e-9 and abs(b.transactions[3]["balance"] - s.rules.default_bankroll) < 1e-9,
      "...each noting the bankroll it left behind")
hist.close(s)

# =============================================================== H. the floor's menus
v = floor_m.Viewport(10, 4)
v.move(-1)
check(v.cursor == 0 and v.top == 0, "Up on the first option stays on it")
for _ in range(12):
    v.move(1)
check(v.cursor == 9 and v.top == 6 and v.more_above and not v.more_below, f"Down stops on the last option, the view scrolled to keep it in sight (top {v.top})")
v.page(-1)
check(v.cursor == 5 and v.top == 5 and list(v.visible) == [5, 6, 7, 8], "Page Up moves a page and the view follows")
v.home()
check(v.cursor == 0 and v.top == 0 and v.more_below, "Home goes back to the top")

check(floor_m.GAMES[0].name == "Classic Blackjack" and floor_m.GAMES[0].bank_key == "blackjack", "the Games menu lists Classic Blackjack")
check([m.title for m in floor_m.Floor().menus] == ["GAMES", "BANK", "DATA"]
      and [i.label for i in floor_m.DATA_ITEMS] == ["Historical Session Data", "P/L Charts", "P/L by Dealer"],
      "three menus: GAMES, BANK, and DATA with Historical Session Data, P/L Charts, and P/L by Dealer")
inch = floor_m.COLUMNS_PER_INCH
games = [floor_m.Game(f"Game {i}", f"g{i}", lambda: None) for i in range(40)]
S.reset_data()
f = floor_m.Floor(games=games)
f.open_bank()
H, W = 60, 238                                                         # about a maximized window on a 13-inch MacBook Pro
lay = f.layout(H, W)
(gy, gx, gh, gw), (by, bx, bh, bw), (dy, dx, dh, dw) = lay.rects
check(lay.fits and lay.sign_y == 2 and len(lay.sign) == 8 and max(len(r) for r in lay.sign) == 220 and (W - 220) // 2 >= floor_m.SIGN_MARGIN,
      "the sign: the marquee row, a blank row, then one line at 1.5x the original size (letters 2 columns apart, room each side)")
check(lay.banner_y == lay.sign_y + len(lay.sign) + 1 and lay.banner_x == 3 * inch and lay.banner_x + lay.banner_w == W - 3 * inch,
      f"a blank row, then the banner, 3 inches ({3 * inch} columns) clear on either side")
check(floor_m.BANNER_TEXT == "Luxury Gaming & Amenities | Making Your Dreams Come True One Bet At A Time", "...reading as it should")
check(gy == by == lay.banner_y + 2 and gx == inch and bx + bw == W - inch and bx - (gx + gw) in (4, 5) and dx == bx and dw == bw == gw,
      f"a blank row, then the menus: 1 inch ({inch} columns) in from each side, the usual gap between the two sides")
check(bh == len(floor_m.BANK_ITEMS) + 2 and dy == by + bh + 1, "BANK ends right after Transactions, DATA starts a row below it")
check(gy + gh == dy + dh == H - math.ceil(H * 0.15) and lay.status_y == gy + gh,
      "GAMES and DATA both end where the bottom 15% of the screen begins, the balance just below")
check(lay.notice == [floor_m.NOTICE] and lay.notice_y == H - 2 and lay.footer_y == H - 3,
      "the notice sits on the row above the marquee, the keys just above it")
narrow = floor_m.Floor().layout(24, 80)
check(narrow.fits and len(narrow.notice) > 1 and narrow.notice_y + len(narrow.notice) == 23 and " ".join(narrow.notice) == floor_m.NOTICE
      and all(len(line) + 2 <= 80 - 4 for line in narrow.notice),
      "in a narrow window the notice wraps, whole, its strip clear of the marquee, still ending just above it")
inside = all(1 <= y and y + h <= H - 1 and 1 <= x and x + w <= W - 1 for y, x, h, w in lay.rects)
check(inside and lay.sign_y >= 1 and lay.notice_y + len(lay.notice) <= H - 1 and lay.banner_x >= 1,
      "nothing on the floor touches the outermost rows and columns -- they're the marquee's")

rows = f.menus[0].view.rows
for _ in range(39):
    f.key(curses.KEY_DOWN)
check(f.menus[0].cursor == 39 and f.menus[0].view.top == 40 - rows and f.menus[0].view.more_above,
      f"a menu longer than its box ({rows} rows) scrolls (viewport) as the highlight moves")
check(f.key(curses.KEY_DOWN) is None and f.focus == 0 and f.menus[0].cursor == 39, "Down on GAMES' last option stays there")
check(f.key(10) == "game:39", "Enter picks the highlighted game")
check(f.key(curses.KEY_RIGHT) is None and f.focus == 1 and f.key(curses.KEY_RIGHT) is None and f.focus == 1, "Right moves into BANK, and stops on that side")
for _ in range(3):
    f.key(curses.KEY_DOWN)
check(f.menus[1].current.label == "Transactions", "(down to Transactions)")
f.key(curses.KEY_DOWN)
check(f.focus == 2 and f.menus[2].cursor == 0, "Down on Transactions carries on into DATA, at its first option")
f.key(curses.KEY_DOWN)
check(f.focus == 2 and f.menus[2].current.action == "data:charts" and f.key(10) == "data:charts", "...down to P/L Charts, which Enter picks")
f.key(curses.KEY_DOWN)
check(f.focus == 2 and f.menus[2].current.action == "data:dealers" and f.key(10) == "data:dealers", "...then P/L by Dealer")
f.key(curses.KEY_DOWN)
check(f.focus == 2 and f.menus[2].cursor == 2, "Down on DATA's last option stays there")
for _ in range(3):
    f.key(curses.KEY_UP)
check(f.focus == 1 and f.menus[1].current.label == "Transactions", "Up on DATA's first option goes back into BANK, at Transactions")
f.key(curses.KEY_DOWN)
f.key(curses.KEY_LEFT)
check(f.focus == 0, "Left goes to GAMES")
f.key(curses.KEY_RIGHT)
check(f.focus == 2, "...and Right back to the right-hand menu last used (DATA)")
check(f.key(9) is None and f.focus == 0 and f.key(9) is None and f.focus == 1 and f.key(curses.KEY_BTAB) is None and f.focus == 0,
      "Tab and Shift-Tab go round all three menus")
f.key(curses.KEY_RIGHT)
where = (f.focus, f.menus[f.focus].cursor)
f.key(27)
check(f.focus is None and f.key(10) is None, "Esc clears the highlight, like clicking off -- and Enter then picks nothing")
f.key(curses.KEY_DOWN)
check((f.focus, f.menus[f.focus].cursor) == where, "the first arrow after that brings the highlight back where it was, without moving it")
check(f.key(ord("q")) == "quit", "q leaves the casino")

deposit_at = (by + 2, bx + 4)
check(f.click(*deposit_at) is None and f.focus == 1 and f.menus[1].current.action == "deposit", "a click highlights the option under it")
check(f.click(*deposit_at) == "deposit", "...and a second click on the highlighted option picks it")
history_at = (dy + 1, dx + 4)
check(f.click(*history_at) is None and f.focus == 2 and f.click(*history_at) == "data:sessions", "the same in DATA")
check(f.click(0, 0) is None and f.focus is None, "a click off the menus clears the highlight")
check(f.click(by, bx + 8) is None and f.focus == 1, "a click on a menu's border moves into that menu")
check(f.click(lay.status_y, lay.leave_x + 2) == "quit", "a click on 'Leave Casino' leaves")
f.wheel(gy + 2, gx + 4, 1)
check(f.focus == 0 and f.menus[0].cursor == 39, "the scroll wheel over a menu moves its highlight (stopping at the end)")

check(not floor_m.Floor().layout(10, 50).fits, "a window too small for the menus says so instead of drawing them")
original = floor_m.fit_sign(170, 40)
check(len(original) == 5 and len(original[0]) == 158 and set("".join(original)) <= {floor_m.BLOCK, " "},
      "the original size is 158 columns x 5 rows of full blocks")
wide = floor_m.fit_sign(260, 40)
check(len(wide) == 8 and len(wide[0]) == 237 and set("".join(wide)) == {floor_m.BLOCK, "▀", "▄", " "},
      "a window with room (245+ columns) gets 1.5x with the font's own spacing: 237 columns x 7 1/2 rows, the half rows in half blocks")
for w in (238, 215, 200, 100):
    rows = floor_m.fit_sign(w, 40)
    check(max(len(r) for r in rows) <= w - 2 * floor_m.SIGN_MARGIN and len(rows) <= 8 and set("".join(rows)) <= {floor_m.BLOCK, "▀", "▄", " "},
          f"in a {w}-column window the sign is on one line, with room either side ({max(len(r) for r in rows)} columns)")
narrow_sign = floor_m.fit_sign(70, 40)
check(len(narrow_sign) == 11 and max(len(r) for r in narrow_sign) <= 70 - 2 * floor_m.SIGN_MARGIN,
      "only a window too narrow for any one-line size (under 87 columns) stacks it, BADDIE'S over CASINO")
check(floor_m.fit_sign(30, 40) == [floor_m.SIGN_TEXT], "...and in a tiny window it's plain text")

f = floor_m.Floor()
f.open_bank()
check(any(label.strip() == "Classic Blackjack" for label, _ in f.summary_lines()), "the account summary lists blackjack's winnings even before it's played")
check(f.move_money("deposit", 0).startswith("Enter an amount") and f.move_money("withdraw", 10_000.01).startswith("You can withdraw at most $10,000.00"),
      "the floor won't move $0, or withdraw more than the balance")
msg = f.move_money("withdraw", 2_500)
check(msg.startswith("Withdrew $2,500.00 -- balance $7,500.00") and bank_m.Bank.open().transactions[-1]["note"] == "Casino floor", f"a withdrawal from the floor: {msg}")
lines = f.transaction_lines()
check(len(lines) == 2 and "Withdrawal" in lines[0] and "-$2,500.00" in lines[0] and "Opening" in lines[1], "transactions list newest first")
check([floor_m.parse_amount(t) for t in ("1,500", "$250.50", "abc")] == [1500.0, 250.5, None], "amounts can be typed with commas or a $")

# =============================================================== I. leaving a game: 'exit' to the floor, 'quit' closes the casino
s = S.make_session(decks=6)
check(commands.handle_command("exit", s) == "Back to the casino floor..." and s.quit_requested and s.leave_to == "floor",
      "'exit' ends the game, headed for the casino floor")
s = S.make_session(decks=6)
check(commands.handle_command("quit", s) == "Closing Baddie's Casino..." and s.quit_requested and s.leave_to == "quit",
      "'quit' ends the game, closing the casino")
check(any(l.split()[0] == "exit" for l in commands.HELP_LINES if l.strip()) and any(l.split()[0] == "quit" for l in commands.HELP_LINES if l.strip()),
      "the help lists them separately")

played = []
fake = floor_m.Game("Fake Game", "fake", lambda: played.append(1) or ("floor" if len(played) < 3 else "quit"))
real_wrapper, real_stdout = floor_m.curses.wrapper, floor_m.sys.stdout
floor_m.curses.wrapper = lambda fn, fl: fake                           # every visit to the floor picks the game again
floor_m.sys.stdout = io.StringIO()                                      # (no maximize request to the real terminal)
try:
    floor_m.run([fake])
finally:
    floor_m.curses.wrapper, floor_m.sys.stdout = real_wrapper, real_stdout
check(len(played) == 3, "the floor takes back a game left with 'exit', and closes with the casino when it's left with 'quit'")

# =============================================================== J. the marquee
marquee_m = importlib.import_module("casino.marquee")
for h, w in ((60, 238), (49, 193), (24, 80), (10, 11)):
    run = marquee_m.slots(h, w)
    edge = set(marquee_m.track(h, w))
    corners = {(0, 0), (0, w - 1), (h - 1, w - 1), (h - 1, 0)}
    lit = marquee_m.lights(h, w, 0)
    order = [i for i, cell in enumerate(run) if cell in lit]
    gaps = {(b - a) % len(run) for a, b in zip(order, order[1:] + order[:1])}
    colors = [lit[run[i]] for i in order]
    alternate = all(a != b for a, b in zip(colors, colors[1:] + colors[:1]))
    check(len(edge) == 2 * (h + w) - 4 and set(run) <= edge and not corners & set(run) and len(run) % 6 == 0,
          f"{w}x{h}: the lights run round every outer cell but the corners (and a few beside them): {len(run)}, a multiple of six")
    check(gaps == {3} and alternate and set(colors) == {"green", "red"},
          f"{w}x{h}: a light every third cell all the way round -- two dark between -- alternating green and red, with no seam")
h, w = 24, 80
run = marquee_m.slots(h, w)
clockwise = {run[i]: run[(i + 1) % len(run)] for i in range(len(run))}
before, after = marquee_m.lights(h, w, 7), marquee_m.lights(h, w, 8)
check(after == {clockwise[cell]: color for cell, color in before.items()}, "each step, every light moves one cell clockwise, keeping its color")
top = lambda step: "".join({"green": "G", "red": "R"}.get(marquee_m.lights(h, w, step).get((0, x)), ".") for x in range(12))
check(top(1)[1:] == top(0)[:-1] and "G..R..G" in top(0), f"along the top they move left to right: {top(0)} -> {top(1)}")
right = [marquee_m.lights(h, w, step).get((5, w - 1)) for step in range(6)]
left = [marquee_m.lights(h, w, step).get((5, 0)) for step in range(6)]
check(sum(c is not None for c in right) == 2 and sum(c is not None for c in left) == 2, "...and down the right side and up the left, just the same")

# =============================================================== K. the line chart
charts_m = importlib.import_module("casino.charts")
c = charts_m.line_chart([0, 10, 20, 30], rows=4, cols=8)
check(c.cells[-1][0] != charts_m.BLANK and c.cells[0][-1] != charts_m.BLANK and c.cells[0][0] == charts_m.BLANK,
      "a rising line starts bottom left and ends top right")
check(c.lo <= 0 <= c.hi and c.zero_row == 3 and [r for r, _ in c.ticks] == sorted(r for r, _ in c.ticks)[::-1] and all(v >= 0 for _, v in c.ticks[1:]),
      "the range takes in $0, and the labels go up the side in order")
rng = random.Random(5)
walk = [0.0]
for _ in range(2000):
    walk.append(walk[-1] + rng.choice((-25, 25, 50, -50, 12.5)))
c = charts_m.line_chart(walk, rows=20, cols=120)
check(all(any(row[col] != charts_m.BLANK for row in c.cells) for col in range(120)) and len(c.cells) == 20 and all(len(r) == 120 for r in c.cells),
      "2,000 rounds across 120 columns: the line is unbroken, every column has a dot")
check(c.lo <= min(walk) and c.hi >= max(walk) and all(c.lo <= v <= c.hi for _, v in c.ticks), "...and stays inside its range, labels included")
check([charts_m.money_label(v) for v in (20000, -2500, 0, 12.5)] == ["+$20,000", "-$2,500", "$0", "+$12.50"], "axis labels read as money")

# =============================================================== L. blackjack's records, for DATA
bjrecords = importlib.import_module("blackjack.records")
data_views = importlib.import_module("casino.data_views")
S.reset_data()
check(bjrecords.sessions() == [] and bjrecords.pl_history().rounds == [], "before blackjack has been played: no sessions, no rounds")
s, hist = launch()
play(s, 25, seed=31)
s.reset_session()
play(s, 12, seed=32)
open_session = hist.session_id
db_bytes = history.DB_PATH.read_bytes()
recs = bjrecords.sessions()
pl = bjrecords.pl_history()
check(history.DB_PATH.read_bytes() == db_bytes and hist.conn.execute("select ended_at from sessions where session_id = ?", (open_session,)).fetchone()[0] is None,
      "reading the records changes nothing -- not even the session still being played")
rows = {r["session_id"]: r for r in hist.conn.execute("select * from sessions")}
check([r.number for r in recs] == sorted(rows, reverse=True) and all(rows[r.number]["hands_played"] == r.hands for r in recs),
      "one record per session, newest first, with its hands")
total = hist.conn.execute("select sum(total_pl) from hands").fetchone()[0]
check(abs(sum(r.total_pl for r in recs) - total) < 1e-6 and all(abs(r.main_pl + r.side_pl - r.total_pl) < 1e-9 for r in recs),
      "their P/L adds up to every hand's")
first = recs[-1]
details = dict(first.details)
low = history.lowest_running_pl(hist.conn, "WHERE session_id = ?", (first.number,))
check(details["Max drawdown"] == bjrecords.money(low) and "Doubles" in details and "Dealer busts" in details,
      f"each session's detail has blackjack's own figures, Max drawdown as the stats screen measures it ({details['Max drawdown']})")
rounds = hist.conn.execute("select count(distinct round_id) from hands").fetchone()[0]
check(len(pl.rounds) == rounds and abs(pl.rounds[-1][1] - total) < 1e-6 and pl.unrecorded == 0,
      f"the P/L history: one point per round ({rounds}), ending at the lifetime P/L, nothing unrecorded")
running = 0.0
ok = True
for (_, value), (round_pl,) in zip(pl.rounds, hist.conn.execute("select sum(total_pl) from hands group by round_id order by min(hand_id)")):
    running += round_pl
    ok = ok and abs(value - running) < 1e-6
check(ok, "...each point the running P/L after its round, from $0")
check(data_views.session_header().split()[0] == "Started" and data_views.session_row(first).count("$") == 4 and
      f"{len(recs)} sessions" in data_views.session_totals(recs), "the session table's rows and totals")
detail = dict(data_views.session_detail(first))
check(detail["Total P/L"] == bjrecords.signed(first.total_pl) and detail["Doubles"] == details["Doubles"], "a session's detail view: the common figures, then blackjack's")

# who dealt: the session detail's "Dealt by", and P/L by Dealer
dealt = {sid: [n for (n,) in hist.conn.execute("select dealer_name from hands where session_id = ? group by dealer_name order by min(hand_id)", (sid,))]
         for sid in rows}
check(all(len(names) == 1 for names in dealt.values()) and dealt[recs[0].number] != dealt[recs[-1].number]
      and all(dict(r.details)["Dealt by"] == dealt[r.number][0] for r in recs) and recs[0].details[0][0] == "Dealt by",
      f"each session's detail opens with who dealt it -- a new dealer for the new session ({dealt})")
table = bjrecords.dealers()
by_name = {d.name: d for d in table.dealers}
ok = True
for r in recs:
    d = by_name[dealt[r.number][0]]
    sess = rows[r.number]
    ok = ok and (d.sessions, d.rounds, d.hands, d.won, d.lost, d.pushed) == (
        1, sess["rounds_played"], sess["hands_played"], sess["hands_won"], sess["hands_lost"], sess["hands_pushed"]
    ) and abs(d.wagered - sess["main_wagered"]) < 1e-6 and abs(d.main_pl - sess["main_pl"]) < 1e-6 and abs(d.side_pl - sess["sidebet_pl"]) < 1e-6
check(ok and len(table.dealers) == 2 and table.unrecorded_hands == 0,
      "P/L by Dealer: each dealer's rounds, hands, W-L-P, wagers, and P/L -- here, exactly their session's")
check([d.total_pl for d in table.dealers] == sorted((d.total_pl for d in table.dealers), reverse=True)
      and abs(sum(d.total_pl for d in table.dealers) - total) < 1e-6, "...best total P/L first, adding up to every hand's")
dealing = s.dealer
commands = importlib.import_module("blackjack.commands")
commands.handle_command(f"fire {dealing}", s)
play(s, 4, seed=33)
names = [n for (n,) in hist.conn.execute("select dealer_name from hands where session_id = ? group by dealer_name order by min(hand_id)", (open_session,))]
newest = bjrecords.sessions()[0]
check(names == [dealing, s.dealer] and dict(newest.details)["Dealt by"] == f"{dealing}, {s.dealer}",
      f"a dealer let go mid-session: both are listed, in the order they dealt ({dict(newest.details)['Dealt by']})")
many = ["Aster", "Barret", "Dong", "Kayla", "Matt", "Oswego", "Raysha", "Steve"]
hist.conn.executemany("update hands set dealer_name = ? where hand_id = ?",
                      [(name, hand_id) for name, (hand_id,) in zip(many, hist.conn.execute(
                          "select min(hand_id) from hands where session_id = ? group by round_id order by 1", (open_session,)))])
hist.conn.commit()
wrapped = [(label, value) for label, value in bjrecords.sessions()[0].details if label in ("Dealt by", "")][:3]
check(len(wrapped) >= 2 and wrapped[0][0] == "Dealt by" and wrapped[1][0] == "" and all(len(v) <= bjrecords.DEALT_BY_WIDTH for _, v in wrapped)
      and ", ".join(v for _, v in wrapped if v).startswith("Aster, Barret, Dong"),
      f"...and a long list wraps onto more lines under the label: {wrapped}")
hist.conn.execute("update hands set dealer_name = null where session_id = ?", (first.number,))
hist.conn.commit()
table = bjrecords.dealers()
old_hands, old_pl = hist.conn.execute("select sum(outcome <> 'abandoned'), sum(total_pl) from hands where session_id = ?", (first.number,)).fetchone()
check(table.unrecorded_hands == old_hands and abs(table.unrecorded_pl - old_pl) < 1e-6
      and dict(bjrecords.sessions()[-1].details)["Dealt by"] == "not recorded (before the dealers)",
      f"play from before dealers were recorded: left out of the table, and counted in its note ({table.unrecorded_hands} hands)")
check(data_views.dealer_header().split()[0] == "Dealer" and data_views.dealer_row(table.dealers[0]).count("$") == 4
      and data_views.dealer_totals(table).startswith(f"{len(table.dealers)} dealer")
      and data_views.unrecorded_note(table).startswith(f"Not included: {old_hands:,} hands from before dealers were recorded")
      and data_views.unrecorded_note(bjrecords.DealerTable()) == "",
      "the dealer table's rows, totals, and note")
hist.close(s)

other = Path(HOME) / "other.db"
s2 = engine.GameSession(10_000.0, rules_m.Rules(), None, None, history=history.HistoryDB.open(other))
s2.ensure_shoe_ready()
play(s2, 3, seed=40)
s2.history.close(s2)
game = floor_m.blackjack_game(other)
check(len(game.sessions()) == 1 and len(game.pl_history().rounds) == 3 and [d.hands for d in game.dealers().dealers] == [3],
      "a blackjack started with --db FILE shows that file's records")
old = Path(HOME) / "old.db"
sqlite3.connect(old).execute("pragma user_version = 2").connection.close()
try:
    bjrecords.sessions(old)
    check(False, "an out-of-date history database is reported")
except S.casino_records.RecordsError as exc:
    check("Open Classic Blackjack once" in str(exc), f"an out-of-date history database says how to fix it: {exc}")

check.finish("check_casino")
