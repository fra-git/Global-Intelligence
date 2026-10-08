"""Cross-edition memory and the output archive.

state/state.json — small JSON the scheduler carries between runs:
  seen       feed items already used (the evening update skips them)
  outlines   front page + item headlines of the latest edition of each kind,
             so the next edition does not repeat them
  week       front pages and scenarios of recent daily reports (for the weekly)
  delivered  sessions already sent, so a backup trigger never sends twice
archive/YYYY-MM-DD/ — every report (markdown + PDF) plus run metadata.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEEN_TTL_HOURS = 36
WEEK_DAYS = 8


class State:
    def __init__(self, directory: Path):
        self.path = directory / "state.json"
        self.data: dict = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        for key in ("seen", "outlines", "delivered"):
            self.data.setdefault(key, {})
        self.data.setdefault("week", [])

    def seen_keys(self, now: datetime) -> set[str]:
        cutoff = now - timedelta(hours=SEEN_TTL_HOURS)
        return {k for k, ts in self.data["seen"].items() if datetime.fromisoformat(ts) >= cutoff}

    def mark_seen(self, keys: list[str], now: datetime) -> None:
        for k in keys:
            self.data["seen"][k] = now.isoformat()
        cutoff = now - timedelta(hours=SEEN_TTL_HOURS)
        self.data["seen"] = {
            k: ts for k, ts in self.data["seen"].items() if datetime.fromisoformat(ts) >= cutoff
        }

    def outline(self, edition: str) -> tuple[str, datetime] | None:
        entry = self.data["outlines"].get(edition)
        if not entry:
            return None
        return entry["text"], datetime.fromisoformat(entry["at"])

    def set_outline(self, edition: str, text: str, now: datetime) -> None:
        self.data["outlines"][edition] = {"text": text, "at": now.isoformat()}

    def add_week_entry(self, date: str, glance: str, scenarios: str) -> None:
        week = [e for e in self.data["week"] if e["date"] != date]
        week.append({"date": date, "glance": glance, "scenarios": scenarios})
        self.data["week"] = sorted(week, key=lambda e: e["date"])[-WEEK_DAYS:]

    def week_memory(self) -> str:
        out = []
        for e in self.data["week"]:
            out += [f"--- Daily report {e['date']} ---", "At a Glance:", e["glance"]]
            if e.get("scenarios"):
                out += ["Scenarios:", e["scenarios"]]
        return "\n".join(out)

    def was_delivered(self, key: str) -> bool:
        return key in self.data["delivered"]

    def mark_delivered(self, key: str, now: datetime) -> None:
        self.data["delivered"][key] = now.isoformat()
        cutoff = now - timedelta(days=WEEK_DAYS)
        self.data["delivered"] = {
            k: ts for k, ts in self.data["delivered"].items() if datetime.fromisoformat(ts) >= cutoff
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))


_H3 = re.compile(r"^###\s+(.+)$", re.MULTILINE)


def outline_of(summary: str, sections: dict[str, str]) -> str:
    """Compact record of an edition: its front-page summary plus every item headline."""
    lines = [summary.strip(), ""]
    for heading, body in sections.items():
        heads = _H3.findall(body)
        if heads:
            lines.append(f"{heading}: " + " | ".join(h.strip() for h in heads))
    return "\n".join(lines).strip()


def prior_context(state: State, edition: str, now: datetime) -> dict[str, str]:
    """Outlines from the last ~24h that this edition should not repeat.

    The daily report is the complete picture, so it only avoids re-reporting the
    previous daily; the evening update builds on that morning's report; the
    weekly reviews everything and repeats freely."""
    wanted = {"DAILY": ["DAILY"], "EVENING": ["DAILY", "WEEKLY"], "WEEKLY": []}[edition]
    out = {}
    for e in wanted:
        got = state.outline(e)
        if got and now - got[1] <= timedelta(hours=26):
            out[f"{e} edition @ {got[1].astimezone(timezone.utc):%d %b %H:%MZ}"] = got[0]
    return out


def archive(directory: Path, edition: str, now: datetime, markdown: str, meta: dict,
            pdf: bytes | None = None) -> Path:
    day = directory / now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    md = day / f"{edition}.md"
    md.write_text(markdown)
    if pdf is not None:
        (day / f"{edition}.pdf").write_bytes(pdf)
    (day / f"{edition}.meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return md
