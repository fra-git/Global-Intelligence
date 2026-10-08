from briefing.postprocess import clean, missing, split_sections, word_count

DRAFT = "## Italy\n\n### Budget\nText.\n\n## 2. European union\n\nEU text.\n## Notes\nstray"


def test_clean_strips_thinking_preamble_and_fence():
    raw = "<thinking>plan</thinking>\nHere are the sections:\n```markdown\n" + DRAFT + "\n```"
    assert clean(raw) == DRAFT


def test_split_matches_loosely_and_demotes_stray_h2():
    got = split_sections(DRAFT, ["Italy", "European Union"])
    assert got["Italy"] == "### Budget\nText."
    assert got["European Union"] == "EU text.\n### Notes\nstray"


def test_missing_sections_detected():
    assert missing(DRAFT, ["Italy", "European Union", "Across Europe"]) == ["Across Europe"]


def test_word_count():
    assert word_count("## Italy\nTwo words") == 3
