"""Dispatch types, their editorial scope, and the daily schedule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import Enum


class DispatchType(str, Enum):
    AM_PART_1 = "AM_PART_1"
    AM_PART_2 = "AM_PART_2"
    PM_PART_1 = "PM_PART_1"
    PM_PART_2 = "PM_PART_2"

    @property
    def session(self) -> str:
        return self.value[:2]  # "AM" | "PM"

    @property
    def part(self) -> int:
        return int(self.value[-1])


@dataclass(frozen=True)
class DispatchSpec:
    type: DispatchType
    title: str
    # Pillars (see config/sources.yaml) whose feed items are sent to the model.
    pillars: tuple[str, ...]
    # How far back feed items are considered fresh for this dispatch.
    lookback_hours: int
    # Section headers that must appear in the output, in order.
    required_sections: tuple[str, ...]
    wants_market_snapshot: bool
    wants_calendar: bool
    # Minimum feed items reserved per actor (EU, US, China, Russia, BRICS+).
    region_quota: int = 4


_PART1_SECTIONS = (
    "INTELLIGENCE BRIEFING | PART 1/2",
    "1. European Core",
    "2. Global Axis",
    "3. Market Ledger",
)
_PART2_SECTIONS = (
    "INTELLIGENCE BRIEFING | PART 2/2",
    "1. Space",
    "2. Deep Tech",
    "3. Energy Transition",
    "4. 24",
)

SPECS: dict[DispatchType, DispatchSpec] = {
    DispatchType.AM_PART_1: DispatchSpec(
        DispatchType.AM_PART_1,
        "Morning Macro, Geopolitics & Markets (overnight recap + European session preview)",
        ("macro", "geo", "energy"),
        lookback_hours=14,
        required_sections=_PART1_SECTIONS,
        wants_market_snapshot=True,
        wants_calendar=True,
    ),
    DispatchType.AM_PART_2: DispatchSpec(
        DispatchType.AM_PART_2,
        "Morning Tech, Space & Forward Catalyst Radar",
        ("tech", "space", "energy"),
        lookback_hours=14,
        required_sections=_PART2_SECTIONS,
        wants_market_snapshot=True,
        wants_calendar=True,
    ),
    DispatchType.PM_PART_1: DispatchSpec(
        DispatchType.PM_PART_1,
        "Evening European Wrap & Global Power Moves (EU close + day's geopolitical outcomes)",
        ("macro", "geo", "energy"),
        lookback_hours=12,
        required_sections=_PART1_SECTIONS,
        wants_market_snapshot=True,
        wants_calendar=True,
    ),
    DispatchType.PM_PART_2: DispatchSpec(
        DispatchType.PM_PART_2,
        "Evening Tech, Space, Industrial Shifts & Overnight Risks",
        ("tech", "space", "energy"),
        lookback_hours=12,
        required_sections=_PART2_SECTIONS,
        wants_market_snapshot=True,
        wants_calendar=True,
    ),
}

# Send windows (UTC). AM lands before the 07:00 UTC European cash open;
# PM lands after the 15:30–16:30 UTC European cash close (DST-dependent).
SESSION_TIMES_UTC: dict[str, time] = {"AM": time(5, 30), "PM": time(17, 0)}


def parts_for(selector: str) -> list[DispatchType]:
    """Resolve a CLI selector: a dispatch type, a session ("AM"/"PM"), or "auto"."""
    sel = selector.upper()
    if sel in DispatchType.__members__:
        return [DispatchType(sel)]
    if sel in ("AM", "PM"):
        return [DispatchType(f"{sel}_PART_1"), DispatchType(f"{sel}_PART_2")]
    if sel == "AUTO":
        return parts_for(session_for(datetime.now(timezone.utc)))
    raise ValueError(f"Unknown dispatch selector: {selector!r}")


def session_for(now: datetime) -> str:
    """AM before 12:00 UTC, PM after."""
    return "AM" if now.astimezone(timezone.utc).hour < 12 else "PM"
