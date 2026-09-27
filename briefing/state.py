"""Cross-dispatch memory and the output archive.

state/            — small JSON the scheduler carries between runs (seen items,
                    last text per dispatch) so AM/PM do not repeat each other.
archive/YYYY-MM-DD/ — every dispatched briefing plus run metadata.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEEN_TTL_HOURS = 36


class State:
    def __init__(self, directory: Path):
        self.path = directory / "state.json"
        self.data: dict = {"seen": {}, "last": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            self.data.setdefault("seen", {})
            self.data.setdefault("last", {})

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

    def last_text(self, dispatch: str) -> tuple[str, datetime] | None:
        entry = self.data["last"].get(dispatch)
        if not entry:
            return None
        return entry["text"], datetime.fromisoformat(entry["at"])

    def set_last(self, dispatch: str, text: str, now: datetime) -> None:
        self.data["last"][dispatch] = {"text": text, "at": now.isoformat()}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))


def prior_context(state: State, dispatch: str, now: datetime) -> dict[str, str]:
    """Briefings from the last ~24h that this dispatch should not repeat.

    Part 2 of a session sees Part 1 of the same session; each part also sees
    its own previous edition (AM<->PM).
    """
    session, part = dispatch[:2], dispatch[-1]
    other_session = "PM" if session == "AM" else "AM"
    wanted = [f"{other_session}_PART_{part}"]
    if part == "2":
        wanted.insert(0, f"{session}_PART_1")
    out = {}
    for d in wanted:
        got = state.last_text(d)
        if got and now - got[1] <= timedelta(hours=20):
            out[f"{d} @ {got[1].astimezone(timezone.utc):%d %b %H:%MZ}"] = got[0]
    return out


def archive(directory: Path, dispatch: str, now: datetime, text: str, meta: dict) -> Path:
    day = directory / now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    md = day / f"{dispatch}.md"
    md.write_text(text)
    (day / f"{dispatch}.meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return md
