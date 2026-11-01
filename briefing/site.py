"""Report archive website: every delivered report, browsable and searchable.

Delivered reports are copied from archive/ into a site folder (the `reports`
branch, served by GitHub Pages) and an index.html is regenerated with each
report's summary and story headlines embedded for client-side search.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

from briefing.dispatch import SPECS, Edition

_H2 = re.compile(r"^## (.+)$", re.MULTILINE)
_H3 = re.compile(r"^### (.+)$", re.MULTILINE)
_MD_INLINE = re.compile(r"\*\*|\*|`|\[([^\]]*)\]\([^)]*\)")


def _plain(text: str) -> str:
    return _MD_INLINE.sub(lambda m: m.group(1) or "", text).strip()


def _sections(md: str) -> dict[str, str]:
    marks = list(_H2.finditer(md))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        body = md[m.end():end]
        out[m.group(1).strip()] = re.split(r"^# ", body, flags=re.MULTILINE)[0].strip()
    return out


def collect(archive_dir: Path, site_dir: Path) -> list[Path]:
    """Copy reports that were actually sent into site_dir/reports/<date>/."""
    copied = []
    for meta_path in sorted(archive_dir.glob("*/*.meta.json")):
        meta = json.loads(meta_path.read_text())
        pdf = meta_path.with_name(meta_path.name.replace(".meta.json", ".pdf"))
        if not meta.get("sent_to") or not pdf.exists():
            continue
        dest = site_dir / "reports" / meta_path.parent.name
        dest.mkdir(parents=True, exist_ok=True)
        stem = meta_path.name.replace(".meta.json", "")
        for suffix in (".pdf", "-phone.pdf", ".md", ".meta.json"):
            src = meta_path.with_name(stem + suffix)
            if src.exists():
                shutil.copy2(src, dest / src.name)
        copied.append(dest / f"{stem}.pdf")
    return copied


def entries(site_dir: Path) -> list[dict]:
    out = []
    for md_path in sorted((site_dir / "reports").glob("*/*.md"), reverse=True):
        try:
            edition = Edition(md_path.stem)
        except ValueError:
            continue
        spec = SPECS[edition]
        meta_path = md_path.with_name(md_path.stem + ".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        sections = _sections(md_path.read_text())
        summary = [_plain(line[2:]) for line in sections.get(spec.summary_heading, "").splitlines()
                   if line.startswith("- ")]
        headlines = [_plain(h) for body in sections.values() for h in _H3.findall(body)]
        out.append({
            "date": md_path.parent.name,
            "edition": edition.value,
            "title": spec.title,
            "pages": meta.get("pages", 0),
            "pdf": f"reports/{md_path.parent.name}/{md_path.stem}.pdf",
            "phone": (f"reports/{md_path.parent.name}/{md_path.stem}-phone.pdf"
                      if md_path.with_name(md_path.stem + "-phone.pdf").exists() else ""),
            "summary": summary[:12],
            "headlines": headlines,
        })
    return out


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Global Intelligence Archive</title>
<style>
:root { --bg:#f7f8fa; --card:#fff; --ink:#1f2937; --muted:#6b7280; --navy:#13294b;
        --accent:#c2410c; --rule:#e5e7eb; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0f141b; --card:#171e27; --ink:#e5e7eb; --muted:#9ca3af; --navy:#8fb3ff;
          --accent:#fb923c; --rule:#263241; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
header { padding:28px 16px 12px; max-width:860px; margin:auto; }
h1 { margin:0 0 4px; font-size:24px; color:var(--navy); }
.sub { color:var(--muted); font-size:14px; }
#q { width:100%; margin-top:14px; padding:11px 14px; font-size:16px; border-radius:10px;
     border:1px solid var(--rule); background:var(--card); color:var(--ink); }
.filters { margin-top:10px; display:flex; gap:8px; flex-wrap:wrap; }
.filters button { border:1px solid var(--rule); background:var(--card); color:var(--ink);
     padding:5px 12px; border-radius:999px; cursor:pointer; font-size:13px; }
.filters button.on { background:var(--navy); color:var(--bg); border-color:var(--navy); }
main { max-width:860px; margin:auto; padding:0 16px 40px; }
h2.month { font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted);
           margin:26px 0 8px; }
.card { background:var(--card); border:1px solid var(--rule); border-radius:12px;
        padding:14px 16px; margin-bottom:10px; }
.top { display:flex; justify-content:space-between; gap:12px; align-items:baseline;
       flex-wrap:wrap; }
.top a { font-weight:600; color:var(--navy); text-decoration:none; font-size:16px; }
.tag { font-size:12px; color:var(--accent); font-weight:600; }
.top a.ph { font-size:13px; font-weight:500; }
.meta { color:var(--muted); font-size:13px; }
details summary { cursor:pointer; color:var(--muted); font-size:13px; margin-top:6px; }
ul { margin:6px 0 0; padding-left:18px; }
li { margin-bottom:4px; font-size:14px; }
mark { background:#fde68a; color:#111; border-radius:3px; }
.empty { color:var(--muted); text-align:center; padding:40px 0; }
</style></head><body>
<header>
  <h1>Global Intelligence Archive</h1>
  <div class="sub">__COUNT__ reports · search across front pages and every story headline</div>
  <input id="q" type="search" placeholder="Search: Ukraine, ECB, Meloni, Taiwan, lithium…"
         autocomplete="off">
  <div class="filters" id="filters">
    <button data-e="" class="on">All</button><button data-e="DAILY">Daily</button>
    <button data-e="EVENING">Evening</button><button data-e="WEEKLY">Weekly</button>
  </div>
</header>
<main id="list"></main>
<script>
const DATA = __DATA__;
const list = document.getElementById("list"), q = document.getElementById("q");
let edition = "";
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const hl = (s, terms) => terms.reduce((t, w) =>
  t.replace(new RegExp("(" + w.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&") + ")", "gi"),
            "<mark>$1</mark>"), esc(s));
function render() {
  const terms = q.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
  let month = "", html = "";
  for (const r of DATA) {
    if (edition && r.edition !== edition) continue;
    const hay = (r.summary.join(" ") + " " + r.headlines.join(" ")).toLowerCase();
    if (!terms.every(t => hay.includes(t))) continue;
    const m = new Date(r.date + "T12:00:00").toLocaleDateString("en-GB",
              {month: "long", year: "numeric"});
    if (m !== month) { html += `<h2 class="month">${m}</h2>`; month = m; }
    const d = new Date(r.date + "T12:00:00").toLocaleDateString("en-GB",
              {weekday: "short", day: "numeric", month: "short"});
    const hits = terms.length ? r.headlines.filter(h => terms.some(t => h.toLowerCase().includes(t))) : [];
    html += `<div class="card"><div class="top"><a href="${r.pdf}">${esc(r.title)} — ${d}</a>
      <span class="meta"><span class="tag">${r.edition}</span>${r.pages ? " · " + r.pages + " pages" : ""}${r.phone ? ` · <a class="ph" href="${r.phone}">phone version</a>` : ""}</span></div>
      ${hits.length ? "<ul>" + hits.slice(0, 6).map(h => "<li>" + hl(h, terms) + "</li>").join("") + "</ul>" : ""}
      ${r.summary.length ? `<details><summary>Front page</summary><ul>` +
        r.summary.map(s => "<li>" + hl(s, terms) + "</li>").join("") + "</ul></details>" : ""}</div>`;
  }
  list.innerHTML = html || '<p class="empty">No reports match.</p>';
}
q.addEventListener("input", render);
document.getElementById("filters").addEventListener("click", e => {
  if (!e.target.dataset || e.target.dataset.e === undefined) return;
  edition = e.target.dataset.e;
  document.querySelectorAll("#filters button").forEach(b => b.classList.toggle("on", b === e.target));
  render();
});
render();
</script></body></html>
"""


def build(site_dir: Path, archive_dir: Path) -> int:
    """Add newly delivered reports to the site and rebuild its index. Returns report count."""
    site_dir.mkdir(parents=True, exist_ok=True)
    collect(archive_dir, site_dir)
    data = entries(site_dir)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = PAGE.replace("__DATA__", payload).replace("__COUNT__", html.escape(str(len(data))))
    (site_dir / "index.html").write_text(page)
    (site_dir / ".nojekyll").write_text("")
    return len(data)
