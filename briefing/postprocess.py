"""Output hygiene: strip non-report text and split a desk's output into its sections."""

from __future__ import annotations

import re

_THINKING = re.compile(r"<thinking>.*?</thinking>\s*", re.DOTALL | re.IGNORECASE)
_FENCE_LINE = re.compile(r"^\s*```[a-z]*\s*$", re.MULTILINE)
_H2 = re.compile(r"^##\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _norm(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", heading.replace("**", "").lower()).strip()


def clean(text: str) -> str:
    text = _THINKING.sub("", text).strip()
    text = _FENCE_LINE.sub("", text)
    # Drop any preamble (or stray H1) before the first section heading.
    m = _H2.search(text)
    if m:
        text = text[m.start():]
    return text.strip()


def split_sections(text: str, headings: tuple[str, ...] | list[str]) -> dict[str, str]:
    """Map each expected heading to its body. Headings are matched loosely (case,
    punctuation, numbering like '1. Italy'); unexpected H2s are demoted to item
    headings (###) inside the previous section."""
    wanted = {_norm(h): h for h in headings}
    found: list[tuple[str, int, int]] = []
    for m in _H2.finditer(text):
        key = re.sub(r"^\d+\s+", "", _norm(m.group(1)))
        if key in wanted and all(h != wanted[key] for h, _, _ in found):
            found.append((wanted[key], m.start(), m.end()))
    out = {}
    for i, (heading, _, body_start) in enumerate(found):
        end = found[i + 1][1] if i + 1 < len(found) else len(text)
        out[heading] = _H2.sub(r"### \1", text[body_start:end]).strip()
    return out


def missing(text: str, headings: tuple[str, ...] | list[str]) -> list[str]:
    got = split_sections(text, headings)
    return [h for h in headings if h not in got]


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))
