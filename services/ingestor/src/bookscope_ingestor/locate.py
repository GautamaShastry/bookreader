"""Resolve a canonical quote to source units, never inventing a unique location.

Quotes are matched against each unit's normalised text separately, so a match can never span a
page/spine boundary. A quote found in more than one place is ``ambiguous`` and must not be
displayed as an exact, verified location.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bookscope_ingestor.models import ParsedDocument
from bookscope_ingestor.normalize import normalize_text


@dataclass(frozen=True)
class QuoteMatch:
    unit_index: int
    start: int
    end: int


@dataclass(frozen=True)
class QuoteResolution:
    status: Literal["unique", "ambiguous", "not_found"]
    matches: tuple[QuoteMatch, ...]

    @property
    def unit_indexes(self) -> tuple[int, ...]:
        return tuple(sorted({m.unit_index for m in self.matches}))


def find_quote(document: ParsedDocument, quote: str) -> QuoteResolution:
    needle = normalize_text(quote)
    if not needle:
        raise ValueError("quote is empty after normalisation")
    matches: list[QuoteMatch] = []
    for unit in document.units:
        if not unit.is_readable:
            continue
        start = unit.normalized_text.find(needle)
        while start != -1:
            matches.append(QuoteMatch(unit.unit_index, start, start + len(needle)))
            start = unit.normalized_text.find(needle, start + 1)
    if not matches:
        return QuoteResolution("not_found", ())
    return QuoteResolution("unique" if len(matches) == 1 else "ambiguous", tuple(matches))
