"""Deterministic fake summary models for offline tests and baselines. No network, no real model.

``ExtractiveFakeModel`` quotes the first sentence of each source as a "claim", so every output is
verifiable against canonical text. Fault switches simulate provider failures, hallucinated
evidence, foreign citations and obedience to prompt injection found in book text. Outputs are
placeholders for workflow testing; they are not summaries and carry no quality signal.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from bookscope_agent_runtime.summary_engine import (
    Claim,
    ModelOutput,
    SourceText,
    Usage,
    prompt_hash,
)
from bookscope_ingestor.chunking import approx_tokens

INJECTION_MARKER = "IGNORE PREVIOUS INSTRUCTIONS"
_SENTENCE = re.compile(r"[^.!?]+[.!?]")


def first_sentence(text: str) -> str:
    match = _SENTENCE.search(text)
    return (match.group(0) if match else text).strip()


@dataclass
class ExtractiveFakeModel:
    model_id: str = "fake-extractive-v1"
    prompt_hash: str = field(default_factory=lambda: prompt_hash("map/v1", "chapter/v1", "book/v1"))
    fail_sources: dict[str, int] = field(default_factory=dict)  # source_id -> failures remaining
    hallucinate_sources: frozenset[str] = frozenset()
    foreign_source_for: frozenset[str] = frozenset()
    obey_injection: bool = False
    delay_seconds: float = 0.0
    map_calls: list[tuple[str, ...]] = field(default_factory=list)

    async def map_block(self, chapter_title: str, sources: Sequence[SourceText]) -> ModelOutput:
        ids = tuple(s.source_id for s in sources)
        self.map_calls.append(ids)
        if self.delay_seconds:
            # later blocks finish first, to prove output order does not depend on completion order
            await asyncio.sleep(self.delay_seconds / (1 + len(self.map_calls)))
        for source in sources:
            remaining = self.fail_sources.get(source.source_id, 0)
            if remaining:
                self.fail_sources[source.source_id] = remaining - 1
                raise RuntimeError("simulated provider 5xx")
        claims: list[Claim] = []
        for source in sources:
            sentence = first_sentence(source.text)
            if source.source_id in self.hallucinate_sources:
                claims.append(
                    Claim(
                        "The book proves the moon is made of cheese.",
                        (source.source_id,),
                        ("made of cheese",),
                    )
                )
                continue
            cited: tuple[str, ...] = (source.source_id,)
            if source.source_id in self.foreign_source_for:
                cited = (source.source_id, "chunk-from-another-owners-book")
            claims.append(Claim(sentence, cited, (sentence,)))
            if self.obey_injection and INJECTION_MARKER in source.text:
                claims.append(
                    Claim(
                        "Secret data from another book.",
                        ("chunk-from-another-owners-book",),
                        (INJECTION_MARKER,),
                    )
                )
        return self._out(sources, claims)

    async def reduce_chapter(self, chapter_title: str, claims: Sequence[Claim]) -> ModelOutput:
        return ModelOutput(tuple(claims[:2]), Usage(sum(approx_tokens(c.text) for c in claims), 40))

    async def reduce_book(self, chapter_claims: Sequence[Sequence[Claim]]) -> ModelOutput:
        picked = tuple(claims[0] for claims in chapter_claims if claims)
        return ModelOutput(picked, Usage(sum(approx_tokens(c.text) for c in picked), 40))

    @staticmethod
    def _out(sources: Sequence[SourceText], claims: list[Claim]) -> ModelOutput:
        tokens = sum(approx_tokens(s.text) for s in sources)
        return ModelOutput(tuple(claims), Usage(tokens, sum(approx_tokens(c.text) for c in claims)))


@dataclass
class ReducerDropsChapterModel(ExtractiveFakeModel):
    """Reducer that silently omits everything after the first chapter (omission fault)."""

    async def reduce_book(self, chapter_claims: Sequence[Sequence[Claim]]) -> ModelOutput:
        first = tuple(chapter_claims[0][:1]) if chapter_claims else ()
        return ModelOutput(first, Usage(10, 10))


@dataclass
class ReducerInventsModel(ExtractiveFakeModel):
    """Chapter reducer that adds an unsupported claim with a fabricated quote."""

    async def reduce_chapter(self, chapter_title: str, claims: Sequence[Claim]) -> ModelOutput:
        invented = Claim("The author recommends a sequel.", claims[0].source_ids, ("a sequel",))
        return ModelOutput((*claims[:2], invented), Usage(20, 20))
