"""Small, explicit value recognisers shared by fast understanding (T0) and the deterministic rule planner, so the two
never disagree about what a flight number or a head count is. Both work on lower-case token lists.

Deliberately conservative: a value is recognised only with clear evidence; anything else is left for a question.
"""

from __future__ import annotations

import re

# Airline names -> IATA codes. A spoken name wins over a (possibly misheard) code: "IndiGo SE 2020" is 6E-2020,
# because speech recognition often hears "6E" as "SE" or "six E".
AIRLINES = {
    "indigo": "6E", "air india": "AI", "air india express": "IX", "spicejet": "SG", "spice jet": "SG",
    "vistara": "UK", "akasa": "QP", "akasa air": "QP", "air asia": "I5", "airasia": "I5", "go first": "G8",
    "emirates": "EK", "singapore airlines": "SQ", "british airways": "BA", "lufthansa": "LH", "qatar": "QR",
    "qatar airways": "QR",
}
CODES = set(AIRLINES.values())

PEOPLE = {"person", "people", "passenger", "passengers", "pax", "adult", "adults", "traveller", "travellers",
          "traveler", "travelers", "seat", "seats", "ticket", "tickets"}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "single": 1, "couple": 2, "both": 2}
PRONOUN_BEFORE_ONE = {"the", "this", "that", "which", "first", "second", "third", "last", "cheapest", "earliest", "1st",
                      "2nd", "3rd"}


def flight_ids(low: list[str]) -> list[tuple[str, list[int]]]:
    """Flight numbers in the tokens, canonical "6E-431", with the token indices they cover.
    Recognised: "6E-431" (typed, any 2-character code with a letter), "6E 431" / "AI 2020" (known airline codes),
    "IndiGo 431", "IndiGo 6E 431", "IndiGo SE 2020" (airline name; a following 2-character code is ignored).
    A bare number is never a flight number."""
    out: list[tuple[str, list[int]]] = []
    i = 0
    while i < len(low):
        w = low[i]
        typed = re.fullmatch(r"([a-z0-9]{2})-(\d{2,4})", w)
        if typed and re.search(r"[a-z]", typed.group(1)):
            out.append((f"{typed.group(1).upper()}-{typed.group(2)}", [i]))
            i += 1
            continue
        name = next((n for n in (3, 2, 1) if " ".join(low[i:i + n]) in AIRLINES), 0)
        if name:
            code, j = AIRLINES[" ".join(low[i:i + name])], i + name
            if j < len(low) and re.fullmatch(r"[a-z0-9]{2}", low[j]) and not low[j].isdigit():
                j += 1  # the code as heard ("6e", "se", "ai"): the airline name decides
            if j < len(low) and re.fullmatch(r"\d{1,4}", low[j]):
                out.append((f"{code}-{low[j]}", list(range(i, j + 1))))
                i = j + 1
                continue
        if w.upper() in CODES and i + 1 < len(low) and re.fullmatch(r"\d{1,4}", low[i + 1]):
            out.append((f"{w.upper()}-{low[i + 1]}", [i, i + 1]))
            i += 2
            continue
        i += 1
    return out


def people_count(low: list[str], exclude: set[int] = frozenset()) -> tuple[int, int] | None:  # type: ignore[assignment]
    """A head count with clear context: "2 passengers", "for two people", "3 travellers", "the two of us",
    "for 2". Returns (count, token index). Never a number that belongs to a flight number (`exclude`), and never the
    pronoun in "the second one"."""
    for i, w in enumerate(low):
        if i in exclude:
            continue
        n = int(w) if w.isdigit() else NUMBER_WORDS.get(w)
        if n is None or n < 1 or n > 20:
            continue
        prev, nxt = (low[i - 1] if i else ""), low[i + 1:i + 3]
        if w == "one" and prev in PRONOUN_BEFORE_ONE:
            continue
        if (nxt and nxt[0] in PEOPLE) or nxt[:2] == ["of", "us"] or (prev == "for" and (not nxt or nxt[0] not in ("the",))):
            return n, i
    return None
