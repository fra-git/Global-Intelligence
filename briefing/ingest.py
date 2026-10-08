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


# Region and topic tagging. An item can carry several tags; each desk receives
# the items matching its tags, with a guaranteed share per tag so a busy story
# (e.g. EU news) cannot crowd out quieter regions (e.g. Africa, Latin America).
_TAG_TERMS: dict[str, tuple[str, ...]] = {
    # --- regions ---
    "it": ("italy", "italian", " rome", "meloni", "mattarella", "milan", "btp", "bank of italy",
           "banca d'italia", "istat", "tajani", "salvini", "schlein", "giorgetti", "palazzo chigi",
           "unicredit", "intesa sanpaolo", "stellantis", "leonardo", "generali", " eni ", "enel",
           "governo", "parlamento", "italia"),
    "eu": ("european union", " eu ", "eu's", "eu-", "brussels", "european commission",
           "von der leyen", "ecb", "lagarde", "eurozone", "euro area", "european parliament",
           "germany", "german", "berlin", "merz", "france", "french", "paris", "macron", "spain",
           "spanish", "madrid", "poland", "polish", "warsaw", "netherlands", "dutch", "belgium",
           "austria", "greece", "greek", "portugal", "sweden", "finland", "denmark", "norway",
           "baltic", "estonia", "latvia", "lithuania", "czech", "hungary", "orban", "slovakia",
           "romania", "bulgaria", "croatia", "serbia", "balkans", "ireland", "switzerland",
           " uk ", "britain", "british", "london", "starmer", "europe"),
    "us": ("united states", "u.s.", " us-", "washington", "white house",
           "trump", "congress", "senate", "pentagon", "fed ", "federal reserve", "powell",
           "treasury", "wall street", "ustr", "commerce department", "nasdaq", "s&p"),
    "cn": ("china", "chinese", "beijing", "xi jinping", "pboc", "yuan", "renminbi", "mofcom",
           "shanghai", "shenzhen", "hong kong", "huawei", "smic", "casc", "taiwan strait"),
    "ru": ("russia", "russian", "moscow", "kremlin", "putin", "rouble", "ruble", "gazprom",
           "rosneft", "urals", "ukraine", "ukrainian", "kyiv", "zelensky", "belarus",
           "shadow fleet"),
    "me": ("israel", "gaza", "west bank", "hamas", "hezbollah", "lebanon", "iran", "tehran",
           "saudi", "riyadh", "uae", "emirates", "abu dhabi", "dubai", "qatar", "doha", "syria",
           "iraq", "yemen", "houthi", "red sea", "turkey", "turkish", "erdogan", "ankara",
           "egypt", "jordan", "gulf", " oman", "kuwait", "bahrain", "middle east"),
    "ip": ("japan", "japanese", "tokyo", "south korea", "korean", "seoul", "north korea",
           "pyongyang", "taiwan", "taipei", "india", "indian", "modi", "new delhi", "pakistan",
           "asean", "indonesia", "vietnam", "philippines", "australia", "thailand", "malaysia",
           "singapore", "bangladesh", "south china sea", "indo-pacific", "asia"),
    "af": ("africa", "african", "nigeria", "kenya", "ethiopia", "sahel", " mali ", " mali's", "malian", " niger ",
           "burkina", "sudan", "congo", "drc", "morocco", "algeria", "tunisia", "libya",
           "senegal", "ghana", "angola", "mozambique", "somalia", "rwanda", "zambia",
           "zimbabwe", "tanzania", "uganda", "cameroon", " chad "),
    "la": ("latin america", "brazil", "brazilian", "lula", "mexico", "mexican", "sheinbaum",
           "argentina", "milei", "chile", "colombia", " peru", "venezuela", "maduro", "ecuador",
           "bolivia", "cuba", "panama", "uruguay", "paraguay", "caribbean", "guatemala",
           "el salvador", "honduras", "nicaragua"),
    "brics": ("brics", "global south", "new development bank", "de-dollar", "rupee", "rbi",
              "south africa", "opec+", "g20"),
    # --- topics ---
    "defence": ("defense", "defence", "military", "army", "navy", "air force", "missile",
                "drone", "nato", "troops", "weapon", " arms ", "munition", "fighter jet",
                "warship", "rheinmetall", "lockheed", "nuclear weapon", "ceasefire", "airstrike",
                " war ", "invasion", "terror"),
    "cyber": ("cyber", "hack", "ransomware", "malware", "data breach", "disinformation",
              "influence operation", "espionage", "phishing", "ddos", "zero-day", "spyware"),
    "tech": (" ai ", "a.i.", "artificial intelligence", "openai", "anthropic", "deepmind",
             "nvidia", "microsoft", "alphabet", "google", " meta ", "apple", "chip",
             "semiconductor", "tsmc", "asml", "data center", "data centre", "quantum", "robot",
             "llm", "deepseek", "alibaba", "tencent", "baidu", "export control", "ai act",
             "software", "startup", "big tech"),
    "space": (" space", "satellite", "rocket", "orbit", "nasa", " esa ", "spacex",
              "starlink", "ariane", "lunar", " moon", " mars", " iss ", "isro", "jaxa",
              "blue origin", "iris²", "iris2"),
    "energy": (" oil", " gas ", "lng", "opec", "brent", "ttf", "pipeline", "electricity",
               "power price", "grid", "nuclear", "renewable", "solar", "wind farm", "battery",
               "lithium", "rare earth", "cobalt", "copper", "critical mineral", "uranium",
               "hydrogen", " coal ", " coal-", "emission", "climate"),
    "econ": ("inflation", "gdp", "growth", "recession", "central bank", "interest rate",
             "rate cut", "rate hike", "ecb", "fed ", "boj", "pboc", "unemployment", "jobs",
             "budget", "deficit", "debt", "imf", "world bank", "oecd", "bond", "yield",
             "spread", "stocks", "shares", "market", "currency", "dollar", " euro ", "yen",
             "bank", "earnings", "tariff", "trade", "sanction", "export", "wto", "economy"),
}
TAGS = tuple(_TAG_TERMS)


def tags_of(text: str) -> tuple[str, ...]:
    t = f" {text.lower()} "
    return tuple(tag for tag in TAGS if any(term in t for term in _TAG_TERMS[tag]))


@dataclass(frozen=True)
class Item:
    source: str
    title: str
    link: str
    published: datetime
    summary: str
    # Tags declared by the feed (e.g. an Italian outlet is always "it").
    feed_tags: tuple[str, ...]
    score: float = 0.0

    @property
    def tags(self) -> tuple[str, ...]:
        found = set(tags_of(f"{self.title} {self.summary}")) | set(self.feed_tags)
        return tuple(t for t in TAGS if t in found)

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
            Item(feed.name, title, e.get("link", ""), published, summary, feed.tags,
                 score(title, summary))
        )
    return items


def fetch_all(feeds: tuple[Feed, ...]) -> tuple[list[Item], dict[str, str]]:
    """Fetch every feed in parallel; return (items, per-feed status)."""
    status: dict[str, str] = {}
    items: list[Item] = []

    def _safe(feed: Feed):
        try:
            return feed, fetch_feed(feed), None
        except Exception as exc:  # one dead feed must never sink an edition
            return feed, [], exc

    with ThreadPoolExecutor(max_workers=8) as pool:
        for feed, got, err in pool.map(_safe, feeds):
            if err:
                log.warning("feed %s failed: %s", feed.name, err)
                status[feed.name] = f"error: {err.__class__.__name__}"
            else:
                status[feed.name] = f"ok ({len(got)})"
                items.extend(got)
    return items, status


def window(items: list[Item], now: datetime, lookback_hours: int,
           seen_keys: set[str] | frozenset[str] = frozenset()) -> list[Item]:
    """Items inside the time window, minus already-used ones, one copy per story."""
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
    return sorted(fresh.values(), key=lambda i: (i.score, i.published), reverse=True)


def select(items: list[Item], tags: tuple[str, ...], limit: int, per_tag: int = 6) -> list[Item]:
    """Pick items matching any of `tags`: up to `per_tag` best items per tag first
    (guaranteed coverage for each region/topic), remaining slots by score.
    `items` must already be ranked (see `window`)."""
    matching = [i for i in items if set(i.tags) & set(tags)]
    picked: dict[str, Item] = {}
    for tag in tags:
        for it in [i for i in matching if tag in i.tags][:per_tag]:
            if len(picked) < limit:
                picked[it.key] = it
    for it in matching:
        if len(picked) >= limit:
            break
        picked.setdefault(it.key, it)
    return sorted(picked.values(), key=lambda i: (i.score, i.published), reverse=True)
