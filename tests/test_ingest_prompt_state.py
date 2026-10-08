from datetime import datetime, timedelta, timezone

from briefing.dispatch import EDITOR, SPECS, Edition, edition_for, session_for
from briefing.ingest import Item, score, select, tags_of, window
from briefing.prompt import build_desk_message, build_editor_message
from briefing.state import State, outline_of, prior_context

NOW = datetime(2026, 10, 8, 3, 50, tzinfo=timezone.utc)  # Thursday 05:50 in Italy


def _item(title, hours_ago, source="FT", summary="", tags=()):
    return Item(source, title, "https://ft.com/x", NOW - timedelta(hours=hours_ago), summary,
                tags, score(title, summary))


def test_window_dedupes_drops_stale_and_seen():
    items = [
        _item("ECB's Lagarde signals pause as BTP-Bund spread widens 12bps", 2),
        _item("ECB’s Lagarde signals pause as BTP–Bund spread widens 12bps", 3, source="Bloomberg"),
        _item("Old ECB story", 30),
        _item("Tariff shock", 1),
    ]
    out = window(items, NOW, 24, {items[3].key})
    assert [i.title for i in out] == ["ECB's Lagarde signals pause as BTP-Bund spread widens 12bps"]


def test_tags_cover_new_regions_and_topics():
    assert set(tags_of("Meloni wins confidence vote in Rome")) >= {"it"}
    assert "me" in tags_of("Houthi attacks disrupt Red Sea shipping")
    assert "af" in tags_of("Junta in Mali expels envoy")
    assert "la" in tags_of("Milei's peso reform lifts Argentina bonds")
    assert "ip" in tags_of("Japan and South Korea hold talks")
    assert "cyber" in tags_of("Ransomware gang hits hospital network")
    assert "space" in tags_of("SpaceX launches 24 Starlink satellites")
    assert tags_of("Plus us and them") == ()


def test_feed_tags_are_added_to_detected_tags():
    it = _item("Il governo approva la manovra", 1, tags=("it",))
    assert "it" in it.tags


def test_select_guarantees_each_tag_a_share():
    eu = [_item(f"ECB Lagarde BTP Bund spread 1{i}bps eurozone Germany France", 1) for i in range(20)]
    africa = _item("Sudan ceasefire talks collapse", 1)
    latam = _item("Brazil central bank holds rates", 1)
    pool = window(eu + [africa, latam], NOW, 24)
    picked = select(pool, ("eu", "af", "la"), limit=10, per_tag=2)
    assert africa in picked and latam in picked and len(picked) == 10
    assert select(pool, ("space",), limit=10) == []


def test_edition_selector_and_dst():
    sunday = datetime(2026, 10, 11, 3, 50, tzinfo=timezone.utc)
    assert edition_for("AM", NOW) is Edition.DAILY
    assert edition_for("AM", sunday) is Edition.WEEKLY
    assert edition_for("pm", NOW) is Edition.EVENING
    assert edition_for("weekly", NOW) is Edition.WEEKLY
    assert edition_for("auto", NOW) is Edition.DAILY
    winter_evening = datetime(2026, 12, 1, 19, 50, tzinfo=timezone.utc)  # 20:50 CET
    assert session_for(winter_evening) == "PM" and edition_for("auto", winter_evening) is Edition.EVENING


def test_every_section_has_a_known_desk_and_unique_heading():
    for spec in SPECS.values():
        desks = {d.key for d in spec.desks} | {EDITOR, "markets"}
        headings = [s.heading for s in spec.sections]
        assert len(headings) == len(set(headings))
        assert all(s.desk in desks for s in spec.sections)
        assert spec.summary_heading in headings
        assert all(spec.sections_for(d.key) for d in spec.desks)


def test_desk_message_lists_sections_items_and_prior():
    spec = SPECS[Edition.DAILY]
    desk = next(d for d in spec.desks if d.key == "economy")
    msg = build_desk_message(
        spec, desk, NOW, [_item("Tariff shock on EU autos", 1)], "- EUR/USD: 1.10",
        [{"time": "2026-10-09T09:00Z", "event": "Ifo"},
         {"time": "2026-10-30T09:00Z", "event": "too far"}],
        {"EVENING edition": "earlier outline"}, searches=7)
    assert "## Energy & Critical Minerals" in msg and "## Italy" not in msg
    assert "Thursday 08 October 2026, 05:50 Italy time" in msg
    assert "at most 7 searches" in msg and "Tariff shock on EU autos" in msg
    assert "<market_snapshot" in msg and "Ifo" in msg and "too far" not in msg
    assert "<already_covered" in msg and "earlier outline" in msg


def test_editor_message_includes_desk_reports_and_week_memory():
    spec = SPECS[Edition.WEEKLY]
    msg = build_editor_message(spec, NOW, "## Italy\n\nbody", [], "Mon: glance", searches=0)
    assert "## Deep Dive" in msg and "## Italy\n\nbody" in msg
    assert "<this_week_daily_reports" in msg and "Do not research" in msg


def test_state_roundtrip_prior_context_week_and_delivery(tmp_path):
    s = State(tmp_path)
    s.set_outline("EVENING", "evening outline", NOW - timedelta(hours=7))
    s.set_outline("DAILY", "yesterday's daily", NOW - timedelta(hours=24))
    s.mark_seen(["abc"], NOW)
    for d in range(10):
        s.add_week_entry(f"2026-10-{d + 1:02d}", f"glance {d}", "")
    s.mark_delivered("2026-10-08:AM", NOW)
    s.save()
    s2 = State(tmp_path)
    assert "abc" in s2.seen_keys(NOW) and s2.was_delivered("2026-10-08:AM")
    ctx = prior_context(s2, "DAILY", NOW)
    assert list(ctx.values()) == ["yesterday's daily"]
    assert prior_context(s2, "DAILY", NOW + timedelta(hours=3)) == {}  # older than 26h
    assert prior_context(s2, "WEEKLY", NOW) == {}
    assert len(s2.data["week"]) == 8 and "glance 9" in s2.week_memory()


def test_outline_lists_item_headlines():
    out = outline_of("- **Top:** x", {"Italy": "intro\n### Budget passes\ntext\n### Strike"})
    assert "Italy: Budget passes | Strike" in out
