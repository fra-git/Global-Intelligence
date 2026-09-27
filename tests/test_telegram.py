from briefing.telegram import split, to_html, to_plain


def test_bold_italic_heading_and_escaping():
    md = "# AM INTELLIGENCE BRIEFING | PART 1/2\n**Macro** & *Implication:* spread <110bp>"
    out = to_html(md)
    assert out.startswith("<b>AM INTELLIGENCE BRIEFING | PART 1/2</b>")
    assert "<b>Macro</b> &amp; <i>Implication:</i> spread &lt;110bp&gt;" in out


def test_bold_inside_italic_template_line():
    out = to_html("*Date: 27 September 2026 | As of: 17:00 UTC*")
    assert out == "<i>Date: 27 September 2026 | As of: 17:00 UTC</i>"


def test_star_bullets_and_arithmetic_are_not_italicised():
    out = to_html("* first\n  - 2*3 = 6 and 5 * 4")
    assert out.startswith("• first")
    assert "<i>" not in out


def test_snake_case_identifiers_untouched():
    assert "<i>" not in to_html("AM_PART_1 and PM_PART_2")


def test_plain_fallback_strips_markup():
    assert to_plain("# T\n**b** *i*") == "T\nb i"


def test_split_respects_limit():
    text = "\n\n".join(["x" * 900] * 10)
    chunks = split(text, 4096)
    assert all(len(c) <= 4096 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
