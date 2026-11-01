import json
import re

from briefing.site import build


def _report(archive, day, edition, md, sent=True, pages=12):
    d = archive / day
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{edition}.pdf").write_bytes(b"%PDF")
    (d / f"{edition}.md").write_text(md)
    (d / f"{edition}.meta.json").write_text(
        json.dumps({"sent_to": [{"chat": "x"}] if sent else [], "pages": pages}))


def test_site_keeps_old_reports_skips_unsent_and_indexes_headlines(tmp_path):
    archive, site = tmp_path / "archive", tmp_path / "site"
    _report(archive, "2026-10-30", "DAILY",
            "# Front Page\n## At a Glance\n- **ECB holds:** see [FT](https://ft.com).\n"
            "# Europe\n## Italy\n### Budget passes </script><b>x</b>\n")
    _report(archive, "2026-10-30", "EVENING", "## What Changed Today\n- **x:** y\n", sent=False)
    assert build(site, archive) == 1
    _report(tmp_path / "archive2", "2026-11-01", "WEEKLY", "## The Week in One Page\n- **W:** z\n")
    assert build(site, tmp_path / "archive2") == 2  # earlier report still listed
    page = (site / "index.html").read_text()
    data = json.loads(re.search(r"const DATA = (.*);\n", page).group(1))
    assert [(r["date"], r["edition"]) for r in data] == [("2026-11-01", "WEEKLY"),
                                                          ("2026-10-30", "DAILY")]
    assert data[1]["summary"] == ["ECB holds: see FT."]
    assert data[1]["headlines"] == ["Budget passes </script><b>x</b>"]
    assert "</script><b>" not in page.split("const DATA = ")[1].split(";\n")[0]
    assert not (site / "reports" / "2026-10-30" / "EVENING.pdf").exists()
    assert (site / ".nojekyll").exists()
