from briefing.telegram import split, to_html, to_plain


def test_bold_italic_heading_and_escaping():
    md = "# DAILY INTELLIGENCE REPORT | 8 OCT\n**Macro** & *Implication:* spread <110bp>"
    out = to_html(md)
    assert out.startswith("<b>DAILY INTELLIGENCE REPORT | 8 OCT</b>")
    assert "<b>Macro</b> &amp; <i>Implication:</i> spread &lt;110bp&gt;" in out


def test_bold_inside_italic_template_line():
    out = to_html("*Date: 27 September 2026 | As of: 17:00 UTC*")
    assert out == "<i>Date: 27 September 2026 | As of: 17:00 UTC</i>"


def test_star_bullets_and_arithmetic_are_not_italicised():
    out = to_html("* first\n  - 2*3 = 6 and 5 * 4")
    assert out.startswith("• first")
    assert "<i>" not in out


def test_dash_bullets_and_links():
    out = to_html("- **Vote:** see [FT](https://ft.com/a_b?x=1&y=2)\n- [bad](javascript:alert(1))")
    assert out.startswith("• <b>Vote:</b> see <a href=\"https://ft.com/a_b?x=1&amp;y=2\">FT</a>")
    assert "javascript" in out and "<a href=\"javascript" not in out


def test_send_document_posts_multipart():
    from briefing.telegram import Telegram

    class Resp:
        ok, headers = True, {"content-type": "application/json"}

        def json(self):
            return {"ok": True, "result": {"message_id": 7}}

    class Session:
        def post(self, url, **kw):
            self.url, self.kw = url, kw
            return Resp()

    http = Session()
    assert Telegram("T", http).send_document("@c", "r.pdf", b"%PDF", "cap") == 7
    assert http.url.endswith("/sendDocument") and http.kw["files"]["document"][0] == "r.pdf"
    assert http.kw["data"] == {"chat_id": "@c", "caption": "cap"}


def test_snake_case_identifiers_untouched():
    assert "<i>" not in to_html("AM_PART_1 and PM_PART_2")


def test_plain_fallback_strips_markup():
    assert to_plain("# T\n**b** *i* [FT](https://ft.com)") == "T\nb i FT (https://ft.com)"


def test_split_respects_limit():
    text = "\n\n".join(["x" * 900] * 10)
    chunks = split(text, 4096)
    assert all(len(c) <= 4096 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
