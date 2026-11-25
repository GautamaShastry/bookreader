"""BS-004: canonical normalisation and offset mapping."""

from __future__ import annotations

import pytest

from bookscope_ingestor.normalize import normalize, normalize_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  a  b\n\tc  ", "a b c"),
        ("ﬁnance", "finance"),  # ligature
        ("été", "été"),  # combining accent composed
        ("a b c", "a b c"),  # NBSP / em space are whitespace
        ("ＡＢ", "AB"),  # full-width
        ("", ""),
        (" \n ", ""),
        ("“quoted” — dash", "“quoted” — dash"),  # punctuation kept
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_offsets_map_back_to_original_substrings() -> None:
    raw = "  The ﬁshing  fleet\nreturns  éarly. "
    n = normalize(raw)
    assert n.text == "The fishing fleet returns éarly."
    assert len(n.source_spans) == len(n.text)
    start = n.text.index("fishing")
    assert n.original_slice(start, start + len("fishing")) == "ﬁshing"
    start = n.text.index("éarly")
    assert n.original_slice(start, start + len("éarly")) == "éarly"
    assert n.original_slice(0, len(n.text)) == "The ﬁshing  fleet\nreturns  éarly."


def test_source_spans_are_monotonic_and_non_empty() -> None:
    n = normalize("a ﬁ b́  c")
    starts = [s for s, _ in n.source_spans]
    assert starts == sorted(starts)
    assert all(a < b for a, b in n.source_spans)


def test_collapsed_space_maps_to_whole_whitespace_run() -> None:
    n = normalize("a \n\t b")
    assert n.text == "a b"
    assert n.original_slice(1, 2) == " \n\t "


def test_empty_span_and_out_of_range_span() -> None:
    n = normalize("abc")
    assert n.source_span(3, 3) == (3, 3)
    with pytest.raises(ValueError, match="outside"):
        n.source_span(1, 9)
