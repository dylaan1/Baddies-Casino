<h1 align="center"><b>Baddie's Casino™</b></h1>

<p align="center"><b>Luxury Gaming &amp; Amenities | Making Your Dreams Come True One Bet At A Time</b></p>

<p align="center">
A full-screen casino for your terminal: walk onto the casino floor, pick a game, and play from one shared bankroll.<br>
<b>Version 1.1.2</b> · <a href="https://github.com/dylaan1/Baddies-Casino/releases">Releases</a> · <a href="BLACKJACK.md">Full guide</a>
</p>

---

## Contents

- [Quick start](#quick-start)
- [How the casino works](#how-the-casino-works)
  - [The casino floor](#the-casino-floor)
  - [The bank](#the-bank)
  - [Your records](#your-records)
  - [Coming and going](#coming-and-going)
- [The games](#the-games)
  - [Classic Blackjack](#classic-blackjack)
- [Installation](#installation)
- [Where your data lives](#where-your-data-lives)
- [Project layout](#project-layout)
- [Testing](#testing)
- [What's new](#whats-new)
- [License](#license)

## Quick start

```bash
git clone https://github.com/dylaan1/Baddies-Casino.git
cd Baddies-Casino
python3 -m casino
```

That opens the casino floor. There's nothing to `pip install`: the casino runs on Python's standard library.
To walk in from any folder, add the shell aliases once (see [Installation](#installation)):

```bash
casino       # the casino floor
blackjack    # straight to the blackjack table
```

## How the casino works

Baddie's Casino is laid out like a real one. You come in through the **casino floor**, sit down at a
**game**, and every game plays from the same **bank**. Every round is written down, so the floor can show
you how you've done.

```
                 ┌──────────────────────────┐
  casino ──────► │       Casino floor       │ ◄────── exit
                 │  Games  ·  Bank  ·  Data │
                 └────────────┬─────────────┘
                              │ pick a game
                              ▼
  blackjack ───► ┌──────────────────────────┐
                 │    Classic Blackjack     │ ─────── quit ──► closes the casino
                 └────────────┬─────────────┘
                              │ wins and losses
                              ▼
                 ┌──────────────────────────┐
                 │   The bank (one balance  │
                 │    for every game)       │
                 └──────────────────────────┘
```

### The casino floor

The floor is the casino's title screen and lobby. A marquee of green and red lights chases clockwise round the
edge of the screen, under the **BADDIE'S CASINO** sign, and three menus sit below it:

| Menu | What's in it |
|---|---|
| **Games** | Every game in the casino. Pick one to sit down at it. |
| **Bank** | **Account Summary** (your balance, what each game has won, your deposits and withdrawals), **Deposit**, **Withdraw**, and **Transactions**. |
| **Data** | **Historical Session Data**, **P/L Charts**, and **P/L by Dealer** for each game (see [Your records](#your-records)). |

Move with the arrow keys (←/→ or Tab to switch menus), pick with Enter, or click an option and click it again.
`q` leaves the casino.

### The bank

Every game plays from **one bankroll**, kept by the casino bank rather than by any one game. The bank keeps two
things apart: what the **games** have won or lost (a running total per game), and what **you** have put in or
taken out (each deposit and withdrawal listed with its date and the balance after it).

```
balance = deposited − withdrawn + what the games have won
```

Move money from the floor's Bank menu, or from inside a game (blackjack's `bank add N`, for example). Each
change is written straight away and safely, so two games open at once never undo each other. A new player
starts with a $10,000.00 opening deposit.

### Your records

Every game logs its play, and the floor's **Data** menu reads it back without changing anything:

- **Historical Session Data**: the game's lifetime totals, then a table of every session (newest first) with
  its length, hands, W-L-P, amount wagered, P/L, and EV. Open a session for its full detail, including who
  dealt it.
- **P/L Charts**: a line chart of the game's running profit and loss, round by round from $0, with its
  current, highest, and lowest points.
- **P/L by Dealer**: how you've done against each dealer, best first: sessions, rounds, hands, W-L-P,
  wagered, P/L, and EV.

### Coming and going

Every game leaves the same two ways, and both save first:

| Command | Does |
|---|---|
| `exit` | Back to the casino floor, however you started the game |
| `quit` | Close Baddie's Casino entirely |

## The games

### Classic Blackjack

A full casino blackjack table built for practicing real-money play and card counting, run the way a real
table runs: cards dealt one at a time, rightmost spot first, with the dealer's peek, insurance and even money,
and surrender.

- **A real table on screen.** Green felt inside a gold rail, the rules printed on the felt, cards with their
  shadows, wagers on chips in casino colors, a shoe that empties (watch the cut card come up) and a discard
  tray that fills.
- **Dealers on rotation.** Ten dealers to start (Aster, Barret, Dong, Kayla, Matt, Oswego, Raysha, Steve, Thi,
  Xiang), named on the felt. A new one takes the table every session and every six shoes, and none deals
  twice in three rotations. `hire` and `fire` change the roster.
- **Your rules, live.** 1–12 decks, fixed or random penetration, 3:2 or 6:5, H17 or S17, late, early, or no
  surrender, double after split, resplitting aces, table limits, and more, all changeable mid-session.
- **Up to three spots**, with splits, resplits, and doubles (face-down options included).
- **Side bets**: Power Poker, Star 21, and Dealer Buster, with adjustable payouts.
- **Card counting**: a live Hi-Lo running and true count (hide it to practice blind) and a bet spread
  reference.
- **Every hand on record** in a SQLite database: lifetime and session stats, exports to CSV, JSON, or MySQL,
  and backups you can restore.

| In a hand | Key |
|---|---|
| Hit / Stand | `SPACE` / `RETURN` |
| Double / Split / Surrender | `D` / `P` / `X` |
| Insurance or even money | `SPACE` yes, `RETURN` no |
| Type a command | `/` (or click the command line), then e.g. `help`, `gamerules`, `dealers` |

Set wagers with the arrow keys (or a click) and digits on the betting grid, then `RETURN` to deal. The
complete guide to every rule, command, and screen is in **[BLACKJACK.md](BLACKJACK.md)**.

## Installation

**Requirements**

- Python 3.9 or later (`python3`)
- macOS or Linux, where Python's `curses` and `sqlite3` modules come built in (on Windows,
  `pip install windows-curses` first)
- A full-screen terminal window. Blackjack needs at least **187 × 50** characters and maximizes the window
  when it starts.

**Shell aliases** (optional): to start the casino, or go straight to a game, from any folder:

```bash
python3 bin/install-aliases      # adds `casino` and `blackjack` to ~/.zshrc (--rc FILE for another shell's)
source ~/.zshrc                  # or open a new terminal
```

Running the installer again (after moving the folder, say) updates the aliases in place, and your shell file
is backed up first whenever it changes.

**Other ways to start**

```bash
python3 -m casino                       # the casino floor
python3 -m blackjack                    # straight to the table
python3 -m blackjack --db practice.db   # play into a separate history file, leaving your main one untouched
```

## Where your data lives

Nothing is kept inside the project folder, so updating the code never touches your money or your history.

| File | Holds |
|---|---|
| `~/.baddies-casino/bank.json` | The casino bank: your balance, deposits, withdrawals, and each game's winnings |
| `~/.cs-blackjack/blackjack.db` | Blackjack's history: every session, shoe, and hand (all its stats come from here) |
| `~/.cs-blackjack_state.json` | Blackjack's table: your rules, wagers, and dealer roster |
| `~/.cs-blackjack/exports/`, `~/.cs-blackjack/backups/` | What blackjack's `export` and `backup` commands write |

(Blackjack's files keep the game's earlier name, `cs-blackjack`, so older saves carry straight on.)

## Project layout

```
Baddies-Casino/
├── casino/         the casino floor, its marquee and Data windows, and the bank
├── blackjack/      Classic Blackjack: the rules engine, the table on screen, history and stats
├── bin/            the launchers behind the `casino` and `blackjack` aliases, and their installer
├── tests/          the test suite and analysis tools
├── BLACKJACK.md    the full guide: the floor, the bank, and every blackjack rule and command
└── README.md
```

## Testing

```bash
python3 -m unittest discover -s tests -v    # the whole suite
python3 tests/check_table.py                # or any one check on its own
```

The checks drive the real game code against known answers, each in a throwaway home folder, so they never
touch your bank or history. The on-screen checks play the real game in a pseudo-terminal and need one extra
package (`pip install pyte`); without it they're skipped. [BLACKJACK.md](BLACKJACK.md#testing) lists what
each check proves.

## What's new

### 1.1.2

- **P/L by Dealer**: a new Data menu view of how you've done against each dealer, best first.
- **Who dealt each session**, at the top of its detail in Historical Session Data.
- **Every shoe and hand records its dealer** in blackjack's history. Shoes dealt since 1.1.1 get theirs
  filled in automatically the first time 1.1.2 opens your history.

### 1.1.1

- **Baddie's Casino** (formerly CasinoSimulations): a casino floor to launch every game from, with a marquee,
  and Games, Bank, and Data menus.
- **One bankroll for every game**, kept by the casino bank, with deposits and withdrawals on record.
- **Your records on the floor**: historical session data and P/L charts.
- **`casino` and `blackjack` shell aliases**, from any folder.
- **A new blackjack table**: felt and a gold rail, squared cards with shadows, chips in casino colors, the
  shoe and discard tray, the dealer's peek, and dealers on rotation (`hire` and `fire`).
- **Side bet payouts repriced**, with odds shown as casinos print them (3:2, 5:2).

## License

Intellectual Property of Dylan Behseresht, 2026. Any unauthorized redistribution of this software without
express written consent is expressly prohibited.
