"""Runtime settings (environment) and YAML source/calendar loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROMPT_PATH = ROOT / "prompts" / "system_prompt.md"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    # Claude Code model alias. "sonnet" keeps four dispatches a day within Pro limits.
    model: str = field(default_factory=lambda: _env("BRIEFING_MODEL", "sonnet"))
    claude_bin: str = field(default_factory=lambda: _env("CLAUDE_BIN", "claude"))
    claude_timeout_s: int = field(default_factory=lambda: int(_env("BRIEFING_TIMEOUT_S", "900")))
    effort: str = field(default_factory=lambda: _env("BRIEFING_EFFORT", "high"))
    max_chars: int = field(default_factory=lambda: int(_env("BRIEFING_MAX_CHARS", "3800")))
    web_search_max_uses: int = field(
        default_factory=lambda: int(_env("BRIEFING_WEB_SEARCH_MAX_USES", "12"))
    )
    telegram_bot_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    telegram_chat_ids: list[str] = field(
        default_factory=lambda: [c.strip() for c in _env("TELEGRAM_CHAT_IDS").split(",") if c.strip()]
    )
    state_dir: Path = field(default_factory=lambda: ROOT / _env("BRIEFING_STATE_DIR", "state"))
    archive_dir: Path = field(default_factory=lambda: ROOT / _env("BRIEFING_ARCHIVE_DIR", "archive"))
    max_feed_items: int = 60


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    pillars: tuple[str, ...]


@dataclass(frozen=True)
class Sources:
    allowed_domains: tuple[str, ...]
    feeds: tuple[Feed, ...]


def load_sources(path: Path = CONFIG_DIR / "sources.yaml") -> Sources:
    data = yaml.safe_load(path.read_text()) or {}
    domains = tuple(data.get("allowed_domains") or ())
    if not 1 <= len(domains) <= 64:
        raise ValueError("allowed_domains must list 1–64 domains (kept small for the tool permission list)")
    feeds = tuple(
        Feed(f["name"], f["url"], tuple(f.get("pillars") or ())) for f in data.get("feeds") or ()
    )
    return Sources(domains, feeds)


def load_calendar(path: Path = CONFIG_DIR / "calendar.yaml") -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return list(data.get("events") or [])


def load_system_prompt(path: Path = PROMPT_PATH) -> str:
    return path.read_text()
