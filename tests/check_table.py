"""The blackjack table's look, apart from the screen: the rules printed on the felt follow the rules the shoe in play
deals by (a change waits for the next shoe), a wager's chip color by its size, the shoe and discard-tray gauge (the
cut card coming up toward the front as the shoe is dealt), the shoe count the red/blue card backs alternate on, and
the dealers -- the rotation (a new one every session and six shoes, none twice in three), 'hire' and 'fire'.
(The table drawn in a terminal is in check_ui.py.)"""
from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()

# =============================================================== the rules on the felt
s = S.make_session(decks=6)
check(ui.felt_rules(s) == "BLACKJACK PAYS 3 TO 2  ·  DEALER STANDS ON SOFT 17  ·  INSURANCE PAYS 2 TO 1",
      f"a 3:2, stand-on-soft-17 table: {ui.felt_rules(s)}")
commands.handle_command("bj65", s)
commands.handle_command("h17", s)
check("3 TO 2" in ui.felt_rules(s) and "STANDS" in ui.felt_rules(s),
      "changing the payout and soft 17 doesn't reprint the felt until the next shoe -- the rules in play haven't changed yet")
s.reset_shoe()
check(ui.felt_rules(s) == "BLACKJACK PAYS 6 TO 5  ·  DEALER HITS ON SOFT 17  ·  INSURANCE PAYS 2 TO 1",
      f"...and the next shoe's felt says so: {ui.felt_rules(s)}")

# =============================================================== the bars at the top
s = S.make_session(decks=6, table_min=25, table_max=5000)
for key in ("power_poker", "star21", "dealer_buster"):
    rule = getattr(s.rules, key)
    rule.enabled, rule.min_bet, rule.max_bet = True, 5, 100
check(ui.table_status_summary(s) == "TABLE: Min $25 – Max $5,000  •  All Side Bets are Min $5 – Max $100",
      f"the red bar: the table's limits, then the side bets' as one range when they share it: {ui.table_status_summary(s)}")
s.rules.dealer_buster.max_bet = 250
check(ui.table_status_summary(s).endswith("Power Poker Min $5 – Max $100  •  Star 21 Min $5 – Max $100  •  Dealer Buster Min $5 – Max $250"),
      "...bet by bet when they don't")
full = ui.table_status_summary(s)
short = ui.table_status_summary(s, len(full) - 1)
check(short == "TABLE: $25–$5,000  •  Power Poker $5–$100  •  Star 21 $5–$100  •  Dealer Buster $5–$250"
      and ui.table_status_summary(s, len(full)) == full,
      f"...and with too little room for the full wording, just the ranges: {short}")
s.rules.star21.enabled = s.rules.dealer_buster.enabled = False
check(ui.table_status_summary(s).endswith("Power Poker is Min $5 – Max $100"), "...just the ones in play")
s.rules.power_poker.enabled = False
check(ui.table_status_summary(s).endswith("No Side Bets"), "...or none")

# =============================================================== chip colors
expected = [
    (1, "white"), (4.5, "white"), (5, "red"), (24.5, "red"), (25, "green"), (99, "green"), (100, "black"), (499, "black"),
    (500, "purple"), (999, "purple"), (1000, "yellow"), (4999, "yellow"), (5000, "orange"), (25000, "orange"),
]
wrong = [(a, c) for a, c in expected if ui.chip_pair(a) != ui.CHIP_PAIRS[c]]
check(not wrong and ui.chip_pair(0) is None,
      f"a wager sits on the biggest chip it reaches: white, red $5, green $25, black $100, purple $500, yellow $1,000, orange $5,000 {wrong}")

# =============================================================== the shoe and the tray
total, cut_left = 312, 78                                              # six decks, cut at 75%
stack, cut = ui.shoe_gauge(total, total, cut_left)
check(stack == ui.SHOE_W and cut == round(ui.SHOE_W * (total - cut_left) / total),
      f"a full shoe fills its box, the cut card three-quarters of the way back ({cut} of {ui.SHOE_W})")
stacks, cuts = [], []
for remaining in range(total, 0, -1):
    st, c = ui.shoe_gauge(total, remaining, cut_left)
    stacks.append(st)
    cuts.append(c)
ahead = [c for c in cuts if c is not None]
check(all(a >= b for a, b in zip(stacks, stacks[1:])) and min(stacks) >= 1,
      "as the shoe is dealt its stack only ever shrinks -- and shows while a card's left")
check(all(a >= b for a, b in zip(ahead, ahead[1:])) and cuts[total - cut_left] is None and all(c is None for c in cuts[total - cut_left:]),
      "...while the cut card comes up toward the front, gone once it's reached")
check(all(c is None or c < st for st, c in zip(stacks, cuts)), "...always inside the stack")
check(ui.shoe_gauge(total, 0, cut_left) == (0, None), "an empty shoe is empty")

# =============================================================== red and blue decks, shoe by shoe
s = S.make_session(decks=6)
first = s.shoe_number
s.reset_shoe()
s.reset_shoe()
check(first >= 1 and s.shoe_number == first + 2, f"the session counts its shoes ({first} -> {s.shoe_number}), which the card backs alternate on")

# =============================================================== the dealers
import random  # noqa: E402

from blackjack import dealers  # noqa: E402
from blackjack.rules import Rules  # noqa: E402

check(Rules().dealers == ["Aster", "Barret", "Dong", "Kayla", "Matt", "Oswego", "Raysha", "Steve", "Thi", "Xiang"],
      "the table starts with ten dealers: Aster, Barret, Dong, Kayla, Matt, Oswego, Raysha, Steve, Thi, Xiang")
s = S.make_session(decks=6)
check(s.dealer in s.rules.dealers and s.rules.recent_dealers[-1:] == [s.dealer] and s.dealer_announced,
      f"a session opens with a dealer from the roster ({s.dealer}) -- no NEW DEALER flash, just there")
on_duty, changes = [s.dealer], []
for shoe in range(2, 6 * 50 + 2):
    s.reset_shoe()
    if not s.dealer_announced:
        changes.append(shoe)
        s.dealer_announced = True
    on_duty.append(s.dealer)
check(changes == list(range(7, 6 * 50 + 2, 6)), f"a new dealer takes over every six shoes: at shoes {changes[:4]}...")
shifts = on_duty[::6]
check(all(len({a, b, c}) == 3 for a, b, c in zip(shifts, shifts[1:], shifts[2:])) and set(shifts) == set(s.rules.dealers),
      f"...never one who dealt either of the last two shifts -- so no one twice in three -- and over 50 shifts, all ten: {shifts[:8]}...")
s.reset_shoe()
leaving = s.dealer
s.reset_session()
check(s.dealer != leaving and not s.dealer_announced, f"a new session brings a new dealer at once ({leaving} -> {s.dealer}), to be announced")
s.dealer_announced = True
for _ in range(5):
    s.reset_shoe()
check(s.dealer_announced, "...and the six shoes count from there")
saved = Rules.from_dict(s.rules.to_dict())
check(saved.dealers == s.rules.dealers and saved.recent_dealers == s.rules.recent_dealers,
      "the roster and the last two dealers are saved with the rules...")
nxt = S.make_session(decks=6)
nxt.rules = saved
nxt.reset_session()
check(nxt.dealer not in s.rules.recent_dealers, f"...so the next session's dealer isn't one who just dealt ({s.rules.recent_dealers} -> {nxt.dealer})")
check(Rules.from_dict({"dealers": "nobody", "recent_dealers": 7}).dealers == list(dealers.STARTING_DEALERS)
      and Rules.from_dict({"dealers": ["Kayla", "kayla", "x1", 5, "Bo"]}).dealers == ["Kayla", "Bo"],
      "a mangled roster in a save file is cleaned up, or the starting ten")
state = random.getstate()
for _ in range(20):
    s.rotate_dealer()
check(random.getstate() == state, "picking a dealer never moves the card shuffle along")
cycle = [dealers.next_dealer(["A", "B", "C"], recent) for recent in (["A", "B"], ["B", "C"], ["C", "A"])]
check(cycle == ["C", "A", "B"], f"with three dealers the rotation is forced: each sits out two shifts ({cycle})")
check(dealers.next_dealer(["A", "B"], ["A", "B"]) == "A" and dealers.next_dealer(["A"], ["A"]) == "A",
      "a roster too short for that (an edited save) still deals: just never the one on now, while there's a choice")

# hire and fire
s = S.make_session(decks=6)
hc = commands.handle_command
check(hc("hire mary jo", s) == "Hired Mary Jo: 11 dealers in the rotation." and hc("hire DeShawn", s).startswith("Hired DeShawn")
      and s.rules.dealers[-2:] == ["Mary Jo", "DeShawn"], "'hire' adds a dealer -- capitalized if typed all lower case, kept as typed otherwise")
check("already on the roster" in hc("hire MARY JO", s) and "12 characters at most" in hc("hire Bartholomewsen", s)
      and "isn't a name" in hc("hire R2D2", s) and hc("hire", s) == "Usage: hire NAME" and len(s.rules.dealers) == 12,
      "...but not twice, nor a name too long for the felt, nor one that isn't a name")
off_duty = next(n for n in s.rules.dealers if n != s.dealer)
check(hc(f"fire {off_duty.lower()}", s) == f"Fired {off_duty}: 11 dealers in the rotation." and off_duty not in s.rules.dealers
      and s.dealer_announced, "'fire' lets a dealer go (any capitalization)")
check(hc("fire Nobody", s).startswith("No dealer named 'Nobody'"), "...naming one who's on the roster")
dealing = s.dealer
check(hc(f"fire {dealing}", s, round_in_progress=True) == f"{dealing} is dealing this round -- finish it first."
      and s.dealer == dealing, "the dealer on duty can't be fired in the middle of a round...")
msg = hc(f"fire {dealing}", s)
check(msg == f"Fired {dealing}. {s.dealer} takes over the table." and s.dealer not in (dealing, None) and not s.dealer_announced,
      f"...but between rounds, the next dealer takes over at once, to be announced: {msg}")
while len(s.rules.dealers) > dealers.MIN_DEALERS:
    hc(f"fire {next(n for n in s.rules.dealers if n != s.dealer)}", s)
check("needs at least 3 dealers" in hc(f"fire {s.rules.dealers[0]}", s) and len(s.rules.dealers) == 3,
      "the rotation keeps at least three dealers")
check(hc("dealers", s).startswith(f"Dealers (3): {', '.join(s.rules.dealers)}.  Dealing: {s.dealer}."),
      f"'dealers' lists the roster and who's dealing: {hc('dealers', s)}")

# =============================================================== the dealer's peek
check(ui.peek_cells(75) == (35, "▒▒▓▒▒") and ui.peek_cells(76) == (35, "▒▒▓▓▒▒"),
      "the peek: five cells on an odd-width border, six on an even one, the middle one or two darker -- dead center either way")

check.finish("check_table")
