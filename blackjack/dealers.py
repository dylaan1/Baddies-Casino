"""The table's dealers: who's on the roster, and who deals next.

A new dealer takes over at the start of every session, and again after every
SHOES_PER_DEALER shoes within one. Each is picked at random from the roster,
leaving out whoever dealt the last REST_ROTATIONS rotations -- so no dealer
comes up more than once in any three rotations in a row. The roster ('hire'
and 'fire') and the last few dealers are saved with the table's rules
(Rules.dealers, Rules.recent_dealers), so the rotation carries on from one
session to the next."""
from __future__ import annotations

import random
import re
from typing import List, Optional, Sequence

STARTING_DEALERS = ("Aster", "Barret", "Dong", "Kayla", "Matt", "Oswego", "Raysha", "Steve", "Thi", "Xiang")
SHOES_PER_DEALER = 6
REST_ROTATIONS = 2  # once a dealer's dealt, they sit out this many rotations: back on the third at the earliest
MIN_DEALERS = REST_ROTATIONS + 1  # the fewest the rotation works with
MAX_NAME_LENGTH = 12  # fits beside the dealer's peek at the smallest window

# Its own generator: picking a dealer never moves the card shuffle along (the
# shoe shuffles with the global one, which the checks seed to repeat a deal).
_rng = random.Random()

_NAME_CHARS = re.compile(r"^[^\W\d_]+(?:[ '.-][^\W\d_]+)*\.?$")


def next_dealer(roster: Sequence[str], recent: Sequence[str], rng: Optional[random.Random] = None) -> Optional[str]:
    """A dealer from `roster` to take over, at random -- never one of the
    last REST_ROTATIONS in `recent` (oldest first), unless the roster's too
    short for that (a hand-edited save file), when it's just never the one
    dealing now. None for an empty roster."""
    if not roster:
        return None
    resting = {name.casefold() for name in recent[-REST_ROTATIONS:]}
    eligible = [name for name in roster if name.casefold() not in resting]
    if not eligible:
        current = recent[-1].casefold() if recent else None
        eligible = [name for name in roster if name.casefold() != current] or list(roster)
    return (rng or _rng).choice(eligible)


def clean_name(raw: str) -> str:
    """A name as it goes on the roster: single-spaced, and capitalized if it
    was typed all in lower case ('mary jo' -> 'Mary Jo'). Raises ValueError
    for anything that isn't a name of up to MAX_NAME_LENGTH characters."""
    name = " ".join(raw.split())
    if not name:
        raise ValueError("Usage: hire NAME")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Dealer names are {MAX_NAME_LENGTH} characters at most ('{name}' is {len(name)}).")
    if not _NAME_CHARS.match(name):
        raise ValueError(f"'{name}' isn't a name: letters, with spaces, hyphens, or apostrophes between them.")
    if name == name.lower():
        name = " ".join(word[:1].upper() + word[1:] for word in name.split(" "))
    return name


def find(roster: Sequence[str], name: str) -> Optional[str]:
    """The roster's spelling of `name` (matched ignoring case), or None."""
    wanted = " ".join(name.split()).casefold()
    return next((entry for entry in roster if entry.casefold() == wanted), None)


def clean_roster(raw: object) -> List[str]:
    """A saved roster, as the game can use it: the names that are names,
    each once. Anything else (a missing or mangled save) is the starting
    ten."""
    if not isinstance(raw, list):
        return list(STARTING_DEALERS)
    roster: List[str] = []
    for entry in raw:
        if isinstance(entry, str):
            try:
                name = clean_name(entry)
            except ValueError:
                continue
            if find(roster, name) is None:
                roster.append(name)
    return roster or list(STARTING_DEALERS)
