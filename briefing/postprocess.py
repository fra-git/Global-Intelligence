"""Output hygiene and template/length validation."""

from __future__ import annotations

import re

from briefing.dispatch import DispatchSpec

_THINKING = re.compile(r"<thinking>.*?</thinking>\s*", re.DOTALL | re.IGNORECASE)
_FENCE_LINE = re.compile(r"^\s*```[a-z]*\s*$", re.MULTILINE)


def tg_len(text: str) -> int:
    """Length as Telegram counts it (UTF-16 code units; flags and emoji count double)."""
    return len(text.encode("utf-16-le")) // 2


def clean(text: str) -> str:
    text = _THINKING.sub("", text).strip()
    text = _FENCE_LINE.sub("", text)
    # Drop any conversational preamble before the template's H1.
    idx = text.find("# ")
    if idx > 0 and "INTELLIGENCE BRIEFING" in text[idx:idx + 80]:
        text = text[idx:]
    return text.strip()


def missing_sections(text: str, spec: DispatchSpec) -> list[str]:
    missing = [s for s in spec.required_sections if s not in text]
    head = text.lstrip().splitlines()[0] if text.strip() else ""
    if spec.type.session not in head:
        missing.insert(0, f"'{spec.type.session}' session label in the H1 header")
    return missing


def hard_trim(text: str, limit: int) -> str:
    """Last resort: cut on a line boundary so no bullet is split mid-sentence."""
    if tg_len(text) <= limit:
        return text
    lines = text.splitlines()
    while lines and tg_len("\n".join(lines) + "\n…") > limit:
        lines.pop()
    return "\n".join(lines).rstrip() + "\n…"
