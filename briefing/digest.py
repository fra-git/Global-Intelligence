"""Option C fallback: an AI-free headline digest in the briefing's shape.

Used when the Claude Code run fails (plan usage limit, expired token, outage).
Only ranked Tier-1 headlines and delayed prices, clearly labelled as such.
"""

from __future__ import annotations

from datetime import datetime, timezone

from briefing.dispatch import DispatchSpec
from briefing.ingest import Item
from briefing.postprocess import tg_len

_REGION_LABELS = [("eu", "🇪🇺 **Europe**"), ("us", "🇺🇸 **US**"), ("cn", "🇨🇳 **China**"),
                  ("ru", "🇷🇺 **Russia**"), ("brics", "🌍 **BRICS+**")]
_PILLAR_LABELS = [("space", "🛰️ **Space & Defense-Tech**"), ("tech", "💻 **Deep Tech & Cyber**"),
                  ("energy", "⚡ **Energy & Critical Materials**")]


def _bullet(it: Item) -> str:
    return f"• {it.title} _({it.source}, {it.published:%H:%MZ})_"


def build(spec: DispatchSpec, now: datetime, items: list[Item], market_block: str | None,
          max_chars: int, per_group: int = 4) -> str:
    dt = now.astimezone(timezone.utc)
    head = [
        f"# {spec.type.session} INTELLIGENCE BRIEFING | PART {spec.type.part}/2",
        "**Headline Digest (analysis unavailable this edition)**",
        f"*Date: {dt:%d %B %Y} | As of: {dt:%H:%M} UTC*",
        "",
    ]
    if spec.type.part == 1:
        # An item tagged EU + another actor is filed under that actor (EU is the default lens).
        def primary(it: Item) -> str | None:
            other = [r for r in it.regions if r != "eu"]
            return other[0] if other else ("eu" if "eu" in it.regions else None)
        groups = [(label, [i for i in items if primary(i) == key]) for key, label in _REGION_LABELS]
    else:
        groups = [(label, [i for i in items if key in i.pillars]) for key, label in _PILLAR_LABELS]

    used: set[str] = set()
    body: list[str] = []
    for label, group in groups:
        picks = [i for i in group if i.key not in used][:per_group]
        if not picks:
            continue
        used.update(i.key for i in picks)
        body += [label, *(_bullet(i) for i in picks), ""]
    if not body:
        body = ["No fresh Tier-1 headlines in the window.", ""]

    tail = []
    if market_block and spec.type.part == 1:
        tail = ["📊 **Market Snapshot (delayed closes)**", market_block, ""]
    footer = ["_Automated Tier-1 headline digest; no analysis was generated for this edition._"]

    lines = head + body + tail + footer
    # Drop the lowest-ranked bullets until it fits.
    while tg_len("\n".join(lines)) > max_chars:
        idx = max((n for n, l in enumerate(lines) if l.startswith("• ")), default=None)
        if idx is None:
            break
        lines.pop(idx)
    return "\n".join(lines).strip()
