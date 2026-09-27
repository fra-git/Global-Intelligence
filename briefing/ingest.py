"""Tier-1 RSS ingestion: fetch, window by time, de-duplicate, rank."""

from __future__ import annotations

import calendar
import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from briefing.config import Feed

log = logging.getLogger(__name__)

USER_AGENT = "GlobalIntelligenceBriefing/0.1 (+rss reader)"
TIMEOUT_S = 15

# Terms that raise an item's rank. Hard-metric and EU-linkage vocabulary is
# weighted because the briefing rejects items without numbers or EU transmission.
_SIGNAL_TERMS = {
    "ecb": 3, "lagarde": 3, "bund": 3, "btp": 3, "oat": 2, "spread": 2, "yield": 2,
    "eurozone": 3, "euro area": 3, "european commission": 3, "brussels": 2, "eu ": 2,
    "germany": 2, "france": 2, "italy": 2, "berlin": 2, "paris": 2,
    "fed": 2, "powell": 2, "treasury": 2, "tariff": 3, "sanction": 3, "export control": 3,
    "china": 3, "beijing": 2, "pboc": 3, "mofcom": 3, "yuan": 2, "taiwan": 2,
    "russia": 3, "kremlin": 2, "ukraine": 2, "urals": 2, "rouble": 2, "ruble": 2, "nato": 2,
    "brics": 3, "india": 2, "brazil": 2, "saudi": 2, "opec": 3, "white house": 2, "ustr": 3,
    "semiconductor": 3, "chip": 2, "asml": 3, "tsmc": 3, "lithography": 3, "ai act": 3,
    "cyber": 2, "cloud": 1, "satellite": 2, "launch": 2, "esa": 3, "ariane": 3,
    "spacex": 2, "starlink": 2, "iris²": 3, "iris2": 3, "lng": 3, "ttf": 3, "brent": 2,
    "gas storage": 3, "rare earth": 3, "lithium": 2, "grid": 2, "nuclear": 2,
    "bps": 2, "basis point": 2, "%": 1, "billion": 1, "bn": 1,
}


# Actor tagging. An item can carry several regions; tags drive per-region quotas
# so EU-heavy news flow cannot crowd the US/China/Russia/BRICS+ picture out.
REGIONS = ("eu", "us", "cn", "ru", "brics")
_REGION_TERMS: dict[str, tuple[str, ...]] = {
    "eu": ("ecb", "eurozone", "euro area", "european", "brussels", "germany", "german", "berlin",
           "france", "french", "paris", "italy", "italian", "rome", "spain", "poland", "netherlands",
           "lagarde", "von der leyen", "bund", "btp", " eu ", "eu's", "nato"),
    "us": ("united states", "u.s.", " us-", "america", "washington", "white house", "trump",
           "congress", "senate", "pentagon", "fed ", "federal reserve", "powell", "treasury",
           "wall street", "ustr", "commerce department", "nasdaq", "s&p"),
    "cn": ("china", "chinese", "beijing", "xi jinping", "pboc", "yuan", "renminbi", "mofcom",
           "shanghai", "shenzhen", "hong kong", "taiwan", "huawei", "smic", "casc"),
    "ru": ("russia", "russian", "moscow", "kremlin", "putin", "rouble", "ruble", "gazprom",
           "rosneft", "urals", "ukraine", "kyiv", "shadow fleet"),
    "brics": ("brics", "india", "indian", "modi", "rbi", "brazil", "lula", "south africa",
              "saudi", "uae", "emirates", "iran", "egypt", "ethiopia", "indonesia", "turkey",
              "opec", "new development bank", "global south", "rupee"),
}


def regions_of(text: str) -> tuple[str, ...]:
    t = f" {text.lower()} "
    return tuple(r for r in REGIONS if any(term in t for term in _REGION_TERMS[r]))


@dataclass(frozen=True)
class Item:
    source: str
    title: str
    link: str
    published: datetime
    summary: str
    pillars: tuple[str, ...]
    score: float = 0.0

    @property
    def regions(self) -> tuple[str, ...]:
        return regions_of(f"{self.title} {self.summary}")

    @property
    def key(self) -> str:
        norm = re.sub(r"[^a-z0-9]+", " ", self.title.lower()).strip()
        return hashlib.sha1(norm.encode()).hexdigest()[:16]


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _entry_time(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None) or entry.get(attr)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def score(title: str, summary: str) -> float:
    text = f" {title} {summary} ".lower()
    s = sum(w for term, w in _SIGNAL_TERMS.items() if term in text)
    s += 2 * len(re.findall(r"\d+(?:\.\d+)?\s?(?:%|bps|bn|billion|mn|million)", text))
    return float(s)


def fetch_feed(feed: Feed) -> list[Item]:
    resp = requests.get(feed.url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    items = []
    for e in parsed.entries:
        published = _entry_time(e)
        title = _strip_html(e.get("title", ""))
        if not published or not title:
            continue
        summary = _strip_html(e.get("summary", ""))[:400]
        items.append(
            Item(feed.name, title, e.get("link", ""), published, summary, feed.pillars,
                 score(title, summary))
        )
    return items


def collect(
    feeds: tuple[Feed, ...],
    pillars: tuple[str, ...],
    now: datetime,
    lookback_hours: int,
    limit: int,
    seen_keys: set[str] | frozenset[str] = frozenset(),
    region_quota: int = 0,
) -> tuple[list[Item], dict[str, str]]:
    """Return (ranked items, per-feed status) for feeds matching `pillars`."""
    selected = [f for f in feeds if set(f.pillars) & set(pillars)]
    status: dict[str, str] = {}
    items: list[Item] = []

    def _safe(feed: Feed):
        try:
            return feed, fetch_feed(feed), None
        except Exception as exc:  # one dead feed must never sink a dispatch
            return feed, [], exc

    with ThreadPoolExecutor(max_workers=8) as pool:
        for feed, got, err in pool.map(_safe, selected):
            if err:
                log.warning("feed %s failed: %s", feed.name, err)
                status[feed.name] = f"error: {err.__class__.__name__}"
            else:
                status[feed.name] = f"ok ({len(got)})"
                items.extend(got)

    return rank(items, now, lookback_hours, limit, seen_keys, region_quota), status


def rank(
    items: list[Item],
    now: datetime,
    lookback_hours: int,
    limit: int,
    seen_keys: set[str] | frozenset[str] = frozenset(),
    region_quota: int = 0,
) -> list[Item]:
    """Freshness window + de-dupe, then pick: up to `region_quota` best items per
    actor first (guaranteed coverage), remaining slots by score."""
    cutoff = now - timedelta(hours=lookback_hours)
    fresh: dict[str, Item] = {}
    for it in items:
        if not (cutoff <= it.published <= now + timedelta(minutes=5)):
            continue
        if it.key in seen_keys:
            continue
        # Same story across outlets: keep the highest-scoring copy.
        if it.key not in fresh or it.score > fresh[it.key].score:
            fresh[it.key] = it
    ordered = sorted(fresh.values(), key=lambda i: (i.score, i.published), reverse=True)
    picked: dict[str, Item] = {}
    if region_quota:
        for region in REGIONS:
            for it in [i for i in ordered if region in i.regions][:region_quota]:
                if len(picked) < limit:
                    picked[it.key] = it
    for it in ordered:
        if len(picked) >= limit:
            break
        picked.setdefault(it.key, it)
    return sorted(picked.values(), key=lambda i: (i.score, i.published), reverse=True)
