"""Telegram delivery: a short summary message, then the full report as a PDF.

The summary is authored in `**bold**` / `*italic*` Markdown. Telegram's own Markdown modes do not treat `**` as bold and choke on
unescaped characters, so we convert to Telegram HTML, which only needs
`& < >` escaped, and fall back to plain text if Telegram still rejects it.
"""

from __future__ import annotations

import html
import logging
import re

import requests

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
TG_LIMIT = 4096

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\*\w])\*(?![\s*])([^*\n]+?)(?<!\s)\*(?![\*\w])")
_UNDERSCORE_ITALIC = re.compile(r"(?<![\w_])_(?![\s_])([^_\n]+?)(?<!\s)_(?![\w_])")
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_LEADING_STAR_BULLET = re.compile(r"^(\s*)\*\s+", re.MULTILINE)
_LEADING_DASH_BULLET = re.compile(r"^(\s*)-\s+", re.MULTILINE)
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)\"]+)\)")


def to_html(md: str) -> str:
    text = html.escape(md, quote=False)
    text = _LEADING_STAR_BULLET.sub(r"\1• ", text)
    text = _LEADING_DASH_BULLET.sub(r"\1• ", text)
    text = _LINK.sub(r'<a href="\2">\1</a>', text)
    text = _HEADING.sub(lambda m: f"<b>{m.group(1).replace('**', '')}</b>", text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    text = _UNDERSCORE_ITALIC.sub(r"<i>\1</i>", text)
    return text


def to_plain(md: str) -> str:
    text = _LINK.sub(r"\1 (\2)", _HEADING.sub(r"\1", md))
    return text.replace("**", "").replace("*", "")


def split(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Split on paragraph/line boundaries; the briefing should fit in one, this is a guard."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        cand = f"{cur}\n\n{para}" if cur else para
        if len(cand) <= limit:
            cur = cand
            continue
        if cur:
            chunks.append(cur)
        while len(para) > limit:
            cut = para.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(para[:cut])
            para = para[cut:].lstrip("\n")
        cur = para
    if cur:
        chunks.append(cur)
    return chunks


class Telegram:
    def __init__(self, token: str, session: requests.Session | None = None):
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set")
        self.token = token
        self.http = session or requests.Session()

    def _call(self, method: str, files: dict | None = None, **payload) -> dict:
        url = API.format(token=self.token, method=method)
        if files:
            r = self.http.post(url, data=payload, files=files, timeout=120)
        else:
            r = self.http.post(url, json=payload, timeout=30)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if not r.ok or not data.get("ok"):
            raise TelegramError(r.status_code, data.get("description", r.text[:200]))
        return data["result"]

    def send_briefing(self, chat_id: str, md: str) -> list[int]:
        ids = []
        try:
            for chunk in split(to_html(md)):
                ids.append(self._call("sendMessage", chat_id=chat_id, text=chunk,
                                      parse_mode="HTML", disable_web_page_preview=True)["message_id"])
        except TelegramError as exc:
            if exc.status != 400 or ids:
                raise
            log.warning("HTML rejected by Telegram (%s); resending as plain text", exc)
            for chunk in split(to_plain(md)):
                ids.append(self._call("sendMessage", chat_id=chat_id, text=chunk,
                                      disable_web_page_preview=True)["message_id"])
        return ids

    def send_document(self, chat_id: str, filename: str, data: bytes, caption: str = "",
                      mime: str = "application/pdf") -> int:
        """Send a file (the PDF report). Caption is plain text, max 1024 characters."""
        res = self._call("sendDocument", files={"document": (filename, data, mime)},
                         chat_id=chat_id, caption=caption[:1024])
        return res["message_id"]

    def get_me(self) -> dict:
        return self._call("getMe")


class TelegramError(RuntimeError):
    def __init__(self, status: int, description: str):
        super().__init__(f"Telegram API {status}: {description}")
        self.status = status
