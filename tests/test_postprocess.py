from briefing.dispatch import SPECS, DispatchType
from briefing.postprocess import clean, hard_trim, missing_sections, tg_len

PART1 = """# PM INTELLIGENCE BRIEFING | PART 1/2
**Macro, Geopolitics & Capital Markets**
🇪🇺 **1. European Core (Policy, ECB, Member States)**
🌐 **2. Global Axis (US, China, Russia, BRICS+)**
📊 **3. Market Ledger & Institutional Sentiment**"""


def test_clean_strips_thinking_preamble_and_fence():
    raw = "<thinking>map items</thinking>\nHere is your briefing:\n```markdown\n" + PART1 + "\n```"
    assert clean(raw) == PART1


def test_valid_template_has_no_missing_sections():
    assert missing_sections(PART1, SPECS[DispatchType.PM_PART_1]) == []


def test_wrong_session_label_detected():
    assert missing_sections(PART1, SPECS[DispatchType.AM_PART_1])


def test_missing_section_detected():
    text = PART1.replace("3. Market Ledger", "3. Markets")
    assert "3. Market Ledger" in missing_sections(text, SPECS[DispatchType.PM_PART_1])


def test_tg_len_counts_utf16():
    assert tg_len("🇪🇺") == 4


def test_hard_trim_on_line_boundary():
    text = "\n".join(f"- line {i} " + "x" * 50 for i in range(200))
    out = hard_trim(text, 3800)
    assert tg_len(out) <= 3800 and out.endswith("…")
