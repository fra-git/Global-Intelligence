"""Assemble an edition's sections into one report: markdown (archive) and PDF (delivery).

Desk output is untrusted (it is built from feed text and web pages), so raw HTML
is neutralised before markdown conversion, only http(s) links survive, and the
PDF renderer is not allowed to fetch any external resource.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

import markdown as md

from briefing.dispatch import MARKETS, EditionSpec, Section, local_now
from briefing.markets import GROUPS, Quote

_MD_EXTENSIONS = ["tables", "sane_lists"]
_SAFE_HREF = re.compile(r'href="(?!https?://)[^"]*"')
_SOURCES_P = re.compile(r"<p><em>(Sources?:)")


def _slug(text: str) -> str:
    return "sec-" + re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _body_html(text: str) -> str:
    text = text.replace("<", "&lt;")
    out = md.markdown(text, extensions=_MD_EXTENSIONS, output_format="html")
    out = _SAFE_HREF.sub('href="#"', out)
    return _SOURCES_P.sub(r'<p class="sources"><em>\1', out)


def _fmt_num(v: float) -> str:
    return f"{v:,.4f}" if abs(v) < 10 else f"{v:,.2f}"


def _pct(v: float | None) -> str:
    if v is None:
        return '<td class="num">–</td>'
    cls = "up" if v > 0 else "down" if v < 0 else ""
    return f'<td class="num {cls}">{v:+.2f}%</td>'


def markets_html(quotes: list[Quote]) -> str:
    if not quotes:
        return "<p><em>Market data unavailable this edition.</em></p>"
    by_label = {q.label: q for q in quotes}
    blocks = []
    for group, instruments in GROUPS.items():
        rows = [by_label[label] for label in instruments if label in by_label]
        if not rows:
            continue
        trs = "".join(
            f"<tr><td>{html.escape(q.label)}</td><td class=\"num\">{_fmt_num(q.last)}</td>"
            f"{_pct(q.change_pct)}{_pct(q.week_pct)}</tr>" for q in rows)
        blocks.append(f'<div class="mkt"><table class="markets"><thead><tr><th>{group}</th>'
                      f'<th class="num">Last</th><th class="num">Day</th><th class="num">Week</th>'
                      f"</tr></thead><tbody>{trs}</tbody></table></div>")
    note = ('<p class="sources"><em>Delayed exchange quotes, last daily close (Yahoo Finance). '
            "Prices, not policy facts.</em></p>")
    return '<div class="mkt-grid">' + "".join(blocks) + "</div>" + note


def markets_markdown(quotes: list[Quote]) -> str:
    if not quotes:
        return "*Market data unavailable this edition.*"
    by_label = {q.label: q for q in quotes}
    lines = ["| Instrument | Last | Day | Week |", "|---|---:|---:|---:|"]
    for instruments in GROUPS.values():
        for label in instruments:
            q = by_label.get(label)
            if q:
                d = f"{q.change_pct:+.2f}%" if q.change_pct is not None else "–"
                w = f"{q.week_pct:+.2f}%" if q.week_pct is not None else "–"
                lines.append(f"| {label} | {_fmt_num(q.last)} | {d} | {w} |")
    return "\n".join(lines)


def assemble_markdown(spec: EditionSpec, now: datetime, bodies: dict[str, str],
                      quotes: list[Quote]) -> str:
    loc = local_now(now)
    out = [f"# {spec.title}", f"*{loc:%A %d %B %Y} — {loc:%H:%M} Italy time*", ""]
    for part in spec.parts:
        out += [f"# {part.title}", ""]
        for s in part.sections:
            body = markets_markdown(quotes) if s.desk == MARKETS else bodies.get(s.heading, "")
            out += [f"## {s.heading}", "", body.strip(), ""]
    return "\n".join(out).strip() + "\n"


CSS = """
@page {
  size: A4; margin: 20mm 17mm 20mm 17mm;
  @top-left { content: string(edition) " · " string(date); font-size: 7.5pt; color: #6b7280; }
  @top-right { content: string(part); font-size: 7.5pt; color: #6b7280; }
  @bottom-center { content: "Page " counter(page) " of " counter(pages);
                   font-size: 7.5pt; color: #6b7280; }
}
@page :first { @top-left { content: none; } @top-right { content: none; } }
:root { --sans: "Noto Sans", "Liberation Sans", "DejaVu Sans", sans-serif;
        --ink: #1f2937; --navy: #13294b; --accent: #c2410c; --muted: #6b7280;
        --box: #eef3fa; --rule: #d6dde8; }
html { font-family: var(--sans); font-size: 10pt; line-height: 1.5; color: var(--ink); }
body { margin: 0; }
.masthead { background: var(--navy); color: #fff; padding: 9mm 8mm 7mm; margin-bottom: 6mm; }
.masthead .brand { font-size: 8.5pt; letter-spacing: .25em; text-transform: uppercase;
                   opacity: .8; }
.masthead h1 { string-set: edition content(); font-size: 24pt; margin: 2mm 0 1mm; line-height: 1.15; }
.masthead .date { string-set: date attr(data-short); font-size: 10.5pt; opacity: .9; }
.masthead .meta { font-size: 8pt; opacity: .7; margin-top: 2mm; }
h1.part { string-set: part attr(data-title); break-before: page; font-size: 17pt; color: #fff;
          background: var(--navy); padding: 4mm 6mm; margin: 0 0 5mm; }
h1.part .num { color: #f9b88b; margin-right: 3mm; }
h2 { font-size: 14pt; color: var(--navy); border-bottom: 2px solid var(--accent);
     padding-bottom: 1.2mm; margin: 7mm 0 3mm; break-after: avoid; }
h3 { font-size: 11pt; color: var(--ink); margin: 5mm 0 1.5mm; break-after: avoid; }
p { margin: 0 0 2.2mm; orphans: 3; widows: 3; text-align: left; }
ul, ol { margin: 0 0 2.5mm; padding-left: 5mm; }
li { margin-bottom: 1.2mm; }
strong { color: #111827; }
a { color: #1d4ed8; text-decoration: none; }
blockquote { background: var(--box); border-left: 3px solid var(--navy); margin: 2.5mm 0 3.5mm;
             padding: 2.5mm 4mm; break-inside: avoid; font-size: 9.3pt; }
blockquote p:last-child { margin-bottom: 0; }
p.sources { font-size: 8pt; color: var(--muted); margin-bottom: 3mm; }
p.sources a { color: var(--muted); text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 4mm; font-size: 8.8pt; }
th { background: var(--navy); color: #fff; text-align: left; padding: 1.5mm 2mm; }
td { border-bottom: 1px solid var(--rule); padding: 1.3mm 2mm; vertical-align: top; }
tr { break-inside: avoid; }
.num { text-align: right; white-space: nowrap; }
td.up { color: #15803d; } td.down { color: #b91c1c; }
.glance { background: var(--box); padding: 4mm 6mm 3mm; border-top: 3px solid var(--accent); }
.glance h2 { margin-top: 0; border: none; }
.toc { break-before: page; }
.toc h2 { margin-top: 0; }
.toc ol { list-style: none; padding: 0; }
.toc li.part { font-weight: 700; color: var(--navy); margin-top: 3mm; }
.toc li.sec { padding-left: 6mm; }
.toc a { color: var(--ink); }
.toc a::after { content: leader('.') target-counter(attr(href), page); color: var(--muted); }
.mkt-grid { display: flex; flex-wrap: wrap; justify-content: space-between; }
.mkt { width: 49%; }
.mkt table { font-size: 8.2pt; }
.footer-note { margin-top: 8mm; font-size: 7.5pt; color: var(--muted); }
"""

_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def render_html(spec: EditionSpec, now: datetime, bodies: dict[str, str], quotes: list[Quote],
                meta_line: str = "") -> str:
    loc = local_now(now)
    title = f"{spec.title} — {loc:%d %B %Y}"
    first, rest = spec.parts[0], spec.parts[1:]

    def section_html(s: Section) -> str:
        body = markets_html(quotes) if s.desk == MARKETS else _body_html(bodies.get(s.heading, ""))
        return f'<h2 id="{_slug(s.heading)}">{html.escape(s.heading)}</h2>{body}'

    out = [
        '<div class="masthead"><div class="brand">Global Intelligence</div>'
        f"<h1>{html.escape(spec.title)}</h1>"
        f'<div class="date" data-short="{loc:%d %B %Y}">{loc:%A %d %B %Y} · {loc:%H:%M} Italy time</div>'
        + (f'<div class="meta">{html.escape(meta_line)}</div>' if meta_line else "")
        + "</div>",
    ]
    glance = first.sections[0]
    out.append(f'<div class="glance">{section_html(glance)}</div>')

    toc = ['<div class="toc"><h2>Contents</h2><ol>']
    for s in first.sections[1:]:
        toc.append(f'<li class="sec"><a href="#{_slug(s.heading)}">{html.escape(s.heading)}</a></li>')
    for i, part in enumerate(rest):
        toc.append(f'<li class="part">{_ROMAN[i]}. {html.escape(part.title)}</li>')
        for s in part.sections:
            toc.append(f'<li class="sec"><a href="#{_slug(s.heading)}">'
                       f"{html.escape(s.heading)}</a></li>")
    toc.append("</ol></div>")
    out += toc
    out += [section_html(s) for s in first.sections[1:]]

    for i, part in enumerate(rest):
        out.append(f'<h1 class="part" data-title="{_ROMAN[i]}. {html.escape(part.title)}">'
                   f'<span class="num">{_ROMAN[i]}</span>'
                   f"{html.escape(part.title)}</h1>")
        out += [section_html(s) for s in part.sections]

    out.append('<p class="footer-note">Compiled automatically from reputable news, official and '
               "research sources with AI-assisted research and writing. Verify critical facts "
               "with the linked sources before acting on them.</p>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body>{''.join(out)}</body></html>")


def _no_fetch(url: str, *args, **kwargs):
    raise ValueError(f"external resource blocked: {url[:80]}")


def render_pdf(page_html: str) -> tuple[bytes, int]:
    """Return (PDF bytes, page count)."""
    from weasyprint import HTML

    doc = HTML(string=page_html, url_fetcher=_no_fetch).render()
    return doc.write_pdf(), len(doc.pages)
