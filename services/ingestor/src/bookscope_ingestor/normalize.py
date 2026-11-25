"""Canonical text normalisation with an exact map back to the original text.

Normalised form: Unicode NFKC, every run of whitespace collapsed to one ASCII space, trimmed.
``NormalizedText.source_spans[i]`` is the ``[start, end)`` range of the original string that
produced normalised character ``i`` (a collapsed space maps to its whole whitespace run), so any
normalised span ``[a, b)`` maps back to ``original[source_spans[a][0] : source_spans[b - 1][1]]``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedText:
    original: str
    text: str
    source_spans: tuple[tuple[int, int], ...]  # one (start, end) per normalised character

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        """Original ``[start, end)`` covering normalised ``[start, end)``."""
        if not 0 <= start <= end <= len(self.text):
            raise ValueError(f"span {start}:{end} outside 0:{len(self.text)}")
        if start == end:
            point = self.source_spans[start][0] if start < len(self.text) else len(self.original)
            return point, point
        return self.source_spans[start][0], self.source_spans[end - 1][1]

    def original_slice(self, start: int, end: int) -> str:
        a, b = self.source_span(start, end)
        return self.original[a:b]


def _clusters(text: str) -> list[tuple[int, int, str]]:
    """Split into (start, end, base + following combining marks) clusters."""
    clusters: list[tuple[int, int, str]] = []
    for index, char in enumerate(text):
        if clusters and unicodedata.combining(char) and not clusters[-1][2].isspace():
            start, _, value = clusters[-1]
            clusters[-1] = (start, index + 1, value + char)
        else:
            clusters.append((index, index + 1, char))
    return clusters


def normalize(text: str) -> NormalizedText:
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    space: tuple[int, int] | None = None  # pending collapsed whitespace run
    for start, end, cluster in _clusters(text):
        for char in unicodedata.normalize("NFKC", cluster):
            if char.isspace():
                if out:
                    space = (space[0], end) if space else (start, end)
                continue
            if space is not None:
                out.append(" ")
                spans.append(space)
                space = None
            out.append(char)
            spans.append((start, end))
    return NormalizedText(original=text, text="".join(out), source_spans=tuple(spans))


def normalize_text(text: str) -> str:
    return normalize(text).text
