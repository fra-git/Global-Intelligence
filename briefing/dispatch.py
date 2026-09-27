"""Dispatch types, their editorial scope, and the daily schedule."""

from __future__ import annotations

from dataclasses import dataclass
import os
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
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
        lookback_hours=11,
        required_sections=_PART1_SECTIONS,
        wants_market_snapshot=True,
        wants_calendar=True,
    ),
    DispatchType.AM_PART_2: DispatchSpec(
        DispatchType.AM_PART_2,
        "Morning Tech, Space & Forward Catalyst Radar",
        ("tech", "space", "energy"),
        lookback_hours=11,
        required_sections=_PART2_SECTIONS,
        wants_market_snapshot=True,
        wants_calendar=True,
    ),
    DispatchType.PM_PART_1: DispatchSpec(
        DispatchType.PM_PART_1,
        "Evening European Wrap & Global Power Moves (EU close + day's geopolitical outcomes)",
        ("macro", "geo", "energy"),
        lookback_hours=16,
        required_sections=_PART1_SECTIONS,
        wants_market_snapshot=True,
        wants_calendar=True,
    ),
    DispatchType.PM_PART_2: DispatchSpec(
        DispatchType.PM_PART_2,
        "Evening Tech, Space, Industrial Shifts & Overnight Risks",
        ("tech", "space", "energy"),
        lookback_hours=16,
        required_sections=_PART2_SECTIONS,
        wants_market_snapshot=True,
        wants_calendar=True,
    ),
}

# Delivery times on the reader's local clock (default Italy, DST-aware).
# AM lands before the 09:00 CET European cash open; PM after the US close.
TIMEZONE = ZoneInfo(os.environ.get("BRIEFING_TZ", "Europe/Rome"))
DELIVERY_LOCAL: dict[str, time] = {"AM": time(6, 0), "PM": time(20, 30)}


def local_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(TIMEZONE)


def utc_offset_hours(now: datetime | None = None) -> float:
    """Current UTC offset of the delivery timezone (Italy: 1 in winter, 2 in summer)."""
    return local_now(now).utcoffset().total_seconds() / 3600


def next_delivery(session: str, now: datetime | None = None) -> datetime:
    """Today's delivery instant for `session` in UTC (may already be in the past)."""
    loc = local_now(now)
    target = datetime.combine(loc.date(), DELIVERY_LOCAL[session], tzinfo=TIMEZONE)
    return target.astimezone(timezone.utc)


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
    """AM before 13:00 local, PM after."""
    return "AM" if local_now(now).hour < 13 else "PM"
