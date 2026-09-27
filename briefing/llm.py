"""Claude API client: research-and-write call with Tier-1-restricted web tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import anthropic

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_CONTINUATIONS = 5
_SERVER_RESULT_TYPES = {"web_search_tool_result", "web_fetch_tool_result"}
_PRE_FALLBACK_DROP = {"thinking", "redacted_thinking", "tool_use"}


class BriefingRefused(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    stop_reason: str
    usage: dict = field(default_factory=dict)
    searches: int = 0
    request_ids: list[str] = field(default_factory=list)


def web_tools(allowed_domains: tuple[str, ...], max_uses: int) -> list[dict]:
    return [
        {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": max_uses,
            "allowed_domains": list(allowed_domains),
        },
        {
            "type": "web_fetch_20260209",
            "name": "web_fetch",
            "max_uses": max(3, max_uses // 2),
            "allowed_domains": list(allowed_domains),
        },
    ]


def final_text(content) -> str:
    """Text of the final answer: text blocks after the last server-tool result.

    With web search, Claude may narrate between searches; only the text that
    follows the last result is the briefing.
    """
    last_tool = -1
    for i, b in enumerate(content):
        if b.type in _SERVER_RESULT_TYPES or b.type == "server_tool_use":
            last_tool = i
    return "".join(b.text for b in content[last_tool + 1:] if b.type == "text").strip()


def _echoable(content) -> list:
    """Assistant content safe to send back on a pause_turn continuation.

    After a mid-output fallback, blocks before the last `fallback` marker that
    belong to the declined model (thinking, tool_use, unpaired server_tool_use)
    must not be echoed.
    """
    fb = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    if fb < 0:
        return list(content)
    result_ids = {getattr(b, "tool_use_id", None) for b in content if b.type in _SERVER_RESULT_TYPES}
    kept = []
    for i, b in enumerate(content):
        if i < fb:
            if b.type in _PRE_FALLBACK_DROP:
                continue
            if b.type == "server_tool_use" and b.id not in result_ids:
                continue
            if b.type not in {"text", "server_tool_use", *_SERVER_RESULT_TYPES}:
                continue
        kept.append(b)
    return kept


class Writer:
    def __init__(self, model: str, effort: str, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic(max_retries=4)
        self.model = model
        self.effort = effort

    def _stream(self, *, system: str, messages: list, tools: list | None, effort: str,
                max_tokens: int):
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            # Frozen system prompt first, cached; volatile content lives in the user turn.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if tools:
            kwargs["tools"] = tools
        with self.client.beta.messages.stream(**kwargs) as stream:
            return stream.get_final_message()

    def run(self, *, system: str, user: str, tools: list | None = None,
            effort: str | None = None, max_tokens: int = 32000) -> LLMResult:
        messages: list = [{"role": "user", "content": user}]
        usage: dict[str, int] = {}
        request_ids: list[str] = []
        searches = 0
        assistant: list = []  # accumulated across pause_turn continuations
        for attempt in range(MAX_CONTINUATIONS + 1):
            msg = self._stream(system=system, messages=messages, tools=tools,
                               effort=effort or self.effort, max_tokens=max_tokens)
            request_ids.append(getattr(msg, "_request_id", "") or "")
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                      "cache_creation_input_tokens"):
                usage[k] = usage.get(k, 0) + (getattr(msg.usage, k, 0) or 0)
            searches += sum(1 for b in msg.content if b.type == "server_tool_use")

            if msg.stop_reason == "refusal":
                details = getattr(msg, "stop_details", None)
                raise BriefingRefused(
                    f"model declined (category={getattr(details, 'category', None)}): "
                    f"{getattr(details, 'explanation', '')}"
                )
            if msg.stop_reason == "pause_turn" and attempt < MAX_CONTINUATIONS:
                # Server-side tool loop hit its iteration cap: echo and resume.
                log.info("pause_turn — resuming (%d/%d)", attempt + 1, MAX_CONTINUATIONS)
                assistant = _echoable(assistant + list(msg.content))
                messages = [messages[0], {"role": "assistant", "content": assistant}]
                continue
            if msg.stop_reason == "max_tokens":
                log.warning("hit max_tokens; output may be truncated")
            return LLMResult(final_text(assistant + list(msg.content)), msg.model, msg.stop_reason, usage,
                             searches, request_ids)
        raise RuntimeError("exceeded pause_turn continuations")
