"""Writer backed by the Claude Code CLI, authenticated with a Claude subscription.

Runs `claude -p` headless, signed in with CLAUDE_CODE_OAUTH_TOKEN (from
`claude setup-token`). Usage counts against the Pro/Max plan limits; there is
no per-token API billing. ANTHROPIC_API_KEY is removed from the child
environment so a stray key can never switch the run to paid API usage.

Tools: WebSearch (instructed to use Tier-1 results only) and WebFetch,
hard-restricted by permission rules to the whitelisted Tier-1 domains.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)

# Variables that would make the CLI bill an API account instead of the subscription.
_PAID_AUTH_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class WriterError(RuntimeError):
    """Claude Code did not produce a usable answer (limits, auth, timeout, crash)."""


@dataclass
class LLMResult:
    text: str
    model: str
    stop_reason: str
    usage: dict = field(default_factory=dict)
    searches: int = 0
    request_ids: list[str] = field(default_factory=list)


def fetch_rules(allowed_domains: tuple[str, ...]) -> list[str]:
    rules = []
    for d in allowed_domains:
        rules += [f"WebFetch(domain:{d})", f"WebFetch(domain:*.{d})"]
    return rules


Runner = Callable[..., subprocess.CompletedProcess]


class Writer:
    def __init__(self, model: str, effort: str, *, binary: str = "claude",
                 timeout_s: int = 900, runner: Runner = subprocess.run):
        self.model = model
        self.effort = effort
        self.binary = binary
        self.timeout_s = timeout_s
        self.runner = runner

    def _command(self, system: str, allowed_domains: tuple[str, ...] | None,
                 effort: str) -> list[str]:
        cmd = [
            self.binary, "-p",
            "--output-format", "json",
            "--model", self.model,
            "--effort", effort,
            "--system-prompt", system,
            "--permission-mode", "dontAsk",  # anything not allowed below is denied
            "--no-session-persistence",
        ]
        if allowed_domains:
            cmd += ["--tools", "WebSearch,WebFetch",
                    "--allowedTools", "WebSearch", *fetch_rules(allowed_domains)]
        else:
            cmd += ["--tools", ""]
        return cmd

    def run(self, *, system: str, user: str, allowed_domains: tuple[str, ...] | None = None,
            effort: str | None = None) -> LLMResult:
        env = {k: v for k, v in os.environ.items() if k not in _PAID_AUTH_VARS}
        if not env.get("CLAUDE_CODE_OAUTH_TOKEN"):
            log.warning("CLAUDE_CODE_OAUTH_TOKEN not set; relying on a local `claude` login")
        cmd = self._command(system, allowed_domains, effort or self.effort)
        # Empty scratch cwd: no project CLAUDE.md or settings leak into the run.
        with tempfile.TemporaryDirectory(prefix="briefing-") as cwd:
            try:
                proc = self.runner(cmd, input=user, capture_output=True, text=True,
                                   timeout=self.timeout_s, env=env, cwd=cwd)
            except subprocess.TimeoutExpired as exc:
                raise WriterError(f"claude timed out after {self.timeout_s}s") from exc
            except FileNotFoundError as exc:
                raise WriterError(f"claude CLI not found ({self.binary})") from exc

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            tail = (proc.stderr or proc.stdout or "")[-300:]
            raise WriterError(f"claude exited {proc.returncode}: {tail}") from exc

        text = (data.get("result") or "").strip()
        if data.get("is_error") or proc.returncode != 0 or not text:
            raise WriterError(
                f"claude failed (exit={proc.returncode}, subtype={data.get('subtype')}): "
                f"{text[:300] or proc.stderr[-300:]}"
            )
        usage = data.get("usage") or {}
        stool = usage.get("server_tool_use") or {}
        models = list((data.get("modelUsage") or {}).keys())
        return LLMResult(
            text=text,
            model=models[0] if models else self.model,
            stop_reason=data.get("stop_reason") or data.get("subtype") or "",
            usage={k: usage.get(k, 0) for k in ("input_tokens", "output_tokens",
                                                "cache_read_input_tokens",
                                                "cache_creation_input_tokens")},
            searches=int(stool.get("web_search_requests", 0)) + int(stool.get("web_fetch_requests", 0)),
            request_ids=[data.get("session_id", "")],
        )
