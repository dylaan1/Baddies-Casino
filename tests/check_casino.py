"""The casino bank (casino/bank.py).

Its balance is always deposits - withdrawals + game winnings; every change is on disk at once and
never undoes another program's; a change that couldn't be written goes in with the next write; a corrupt file
is set aside, never overwritten. Blackjack's old bankroll moves in exactly once, split into what was deposited
and what blackjack won, and is never lost if the bank can't be created; blackjack's bank commands land as
deposits/withdrawals and its table results as winnings."""
import json
import os
import random
from pathlib import Path

from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()
bank_m = S.casino_bank
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
b = bank_m.Bank.open(opening=S.bjbank.opening)                          # another program sharing the bank, before blackjack has run
check(abs(b.balance - 777) < 1e-9 and abs(b.game_winnings["blackjack"] - 77) < 1e-9, "another program opening the bank first carries the bankroll over the same way")
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

check.finish("check_casino")
