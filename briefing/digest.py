"""AI-free fallback: headline digests for sections whose desk could not run.

Used when a Claude Code run fails (plan usage limit, expired token, outage).
The rest of the report is still produced; the affected sections list ranked
headlines from the feeds, clearly labelled as such.
"""

from __future__ import annotations

from briefing.ingest import Item

NOTE = ("*Automated headline digest: the analysis for this section could not be generated "
        "this edition (Claude usage limit or outage).*")


def _line(it: Item) -> str:
    title = it.title.replace("[", "(").replace("]", ")")
    head = f"[{title}]({it.link})" if it.link else title
    out = f"- **{head}** — {it.source}, {it.published:%d %b %H:%M} UTC"
    if it.summary:
        out += f"  \n  {it.summary[:280]}"
    return out


def section(items: list[Item], limit: int = 8) -> str:
    if not items:
        return NOTE + "\n\nNo fresh headlines from the feeds for this section."
    return NOTE + "\n\n" + "\n".join(_line(i) for i in items[:limit])


def glance(items: list[Item], limit: int = 10) -> str:
    """Front-page fallback when the editor run fails: the top-ranked headlines."""
    if not items:
        return "No fresh headlines available."
    return ("*Top headlines by relevance (editor summary unavailable this edition).*\n\n"
            + "\n".join(f"- **{i.title}** ({i.source})" for i in items[:limit]))
