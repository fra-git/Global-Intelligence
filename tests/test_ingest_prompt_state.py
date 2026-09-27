from datetime import datetime, timedelta, timezone

from briefing.dispatch import SPECS, DispatchType, parts_for, session_for
from briefing.ingest import Item, rank, score
from briefing.prompt import build_user_message
from briefing.state import State, prior_context

NOW = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)


def _item(title, hours_ago, source="FT", summary=""):
    return Item(source, title, "https://ft.com/x", NOW - timedelta(hours=hours_ago), summary,
                ("macro",), score(title, summary))


def test_rank_windows_dedupes_and_orders():
    items = [
        _item("ECB's Lagarde signals pause as BTP-Bund spread widens 12bps", 2),
        _item("ECB’s Lagarde signals pause as BTP–Bund spread widens 12bps", 3, source="Bloomberg"),
        _item("Local sports result", 1),
        _item("Old ECB story", 30),
    ]
    out = rank(items, NOW, 12, 10)
    assert [i.title for i in out][0].startswith("ECB's Lagarde")
    assert len(out) == 2  # cross-outlet dupe collapsed, stale dropped


def test_rank_skips_seen():
    it = _item("Tariff shock", 1)
    assert rank([it], NOW, 12, 10, {it.key}) == []


def test_parts_for_selectors():
    assert parts_for("pm") == [DispatchType.PM_PART_1, DispatchType.PM_PART_2]
    assert parts_for("AM_PART_2") == [DispatchType.AM_PART_2]
    assert session_for(NOW) == "PM"


def test_user_message_contains_variables_and_blocks():
    msg = build_user_message(
        SPECS[DispatchType.PM_PART_1], NOW, [_item("Tariff shock on EU autos", 1)],
        "- EUR/USD: 1.10", [{"time": "2026-09-28T09:00Z", "event": "Ifo"},
                            {"time": "2026-10-05T09:00Z", "event": "too far"}],
        {"AM_PART_1 @ 27 Sep 05:30Z": "earlier text"}, 3800,
    )
    assert "DISPATCH_TYPE: PM_PART_1" in msg
    assert "DATETIME: 27 September 2026 | 17:00 UTC" in msg
    assert "Ifo" in msg and "too far" not in msg
    assert "<market_snapshot" in msg and "<already_dispatched" in msg


def test_state_roundtrip_and_prior_context(tmp_path):
    s = State(tmp_path)
    s.set_last("PM_PART_1", "part one text", NOW)
    s.set_last("AM_PART_2", "morning part two", NOW - timedelta(hours=11))
    s.mark_seen(["abc"], NOW)
    s.save()
    s2 = State(tmp_path)
    assert "abc" in s2.seen_keys(NOW)
    ctx = prior_context(s2, "PM_PART_2", NOW)
    assert any(k.startswith("PM_PART_1") for k in ctx)
    assert any(k.startswith("AM_PART_2") for k in ctx)


def test_regions_tagging():
    from briefing.ingest import regions_of
    assert regions_of("Beijing tightens rare earth export curbs on EU carmakers") == ("eu", "cn")
    assert "ru" in regions_of("Kremlin reroutes Urals crude via shadow fleet")
    assert "brics" in regions_of("BRICS summit: India pushes rupee settlement")
    assert "us" in regions_of("U.S. Treasury widens sanctions")
    assert regions_of("Plus us and them") == ()


def test_region_quota_protects_non_eu_coverage():
    eu = [_item(f"ECB Lagarde BTP Bund spread 1{i}bps eurozone Germany France", 1) for i in range(20)]
    ru = _item("Kremlin shifts policy", 1)
    cn = _item("PBoC trims rate", 1)
    plain = rank(eu + [ru, cn], NOW, 12, 10)
    assert ru not in plain and cn not in plain
    quota = rank(eu + [ru, cn], NOW, 12, 10, region_quota=2)
    assert ru in quota and cn in quota and len(quota) == 10


def test_italy_delivery_times_follow_dst():
    from briefing.dispatch import next_delivery, session_for, utc_offset_hours
    summer = datetime(2026, 7, 1, 3, 15, tzinfo=timezone.utc)   # 05:15 CEST
    winter = datetime(2026, 12, 1, 4, 15, tzinfo=timezone.utc)  # 05:15 CET
    assert utc_offset_hours(summer) == 2 and utc_offset_hours(winter) == 1
    assert next_delivery("AM", summer) == datetime(2026, 7, 1, 4, 0, tzinfo=timezone.utc)
    assert next_delivery("AM", winter) == datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc)
    assert next_delivery("PM", summer) == datetime(2026, 7, 1, 18, 30, tzinfo=timezone.utc)
    assert next_delivery("PM", winter) == datetime(2026, 12, 1, 19, 30, tzinfo=timezone.utc)
    assert session_for(summer) == "AM"
    assert session_for(datetime(2026, 12, 1, 18, 45, tzinfo=timezone.utc)) == "PM"
