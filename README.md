# Global Intelligence

An automated pipeline that writes executive intelligence briefings centred on the EU and posts them to Telegram. It sends **four dispatches a day** in two sessions (AM and PM, each Part 1 and Part 2). The writing is done by **Claude Code running on a Claude Pro subscription** (no API billing), with web research limited to Tier-1 sources. Every briefing must follow a fixed template and stay under 3,800 characters. If Claude is unavailable (plan limit reached, expired token, outage), that edition goes out as an **AI-free headline digest** instead.

## Architecture

```
            ┌──────────────── GitHub Actions cron (05:10 / 16:40 UTC) ────────────────┐
            │                                                                          │
 config/sources.yaml ──► ingest.py ──┐                                                 │
   (Tier-1 RSS feeds,     fetch ∥,   │                                                 │
    domain whitelist)     window,    │                                                 │
                          dedupe,    │                                                 │
                          rank       ▼                                                 │
 markets.py ─────────────────► prompt.py ──► llm.py ──────────► postprocess.py         │
   (EUR/USD, Brent, TTF,        user turn     `claude -p` on       strip, validate     │
    VIX, indices, UST10Y)       (volatile)    Pro subscription     template, length    │
 config/calendar.yaml ────────►      ▲        WebSearch + WebFetch    │   ▲            │
   (next-48h catalysts)              │        (Tier-1 domains only)   │   │ repair /   │
 state.py ───────────────────────────┘        on failure:             │   │ compress   │
   (prior dispatches, seen items)             digest.py (option C)    ▼   │ (≤2 passes)│
                                                                   telegram.py         │
                                                          Markdown → Telegram HTML,    │
                                                          plain-text fallback          │
                                                                      │                │
                                        archive/YYYY-MM-DD/*.md + meta.json ◄──────────┘
```

| Stage | Module | What it guarantees |
|---|---|---|
| Source registry | `config/sources.yaml` | Only whitelisted Tier-1 domains can be searched or fetched; banned sources can't be reached. |
| Ingestion | `briefing/ingest.py` | Pulls feeds in parallel. Keeps only items inside the dispatch's time window, merges the same story from different outlets, and ranks items higher when they carry hard numbers or an EU link. A dead feed is logged and skipped. |
| Market anchors | `briefing/markets.py` | Delayed prices, kept in their own `<market_snapshot>` block so market pricing never mixes with official facts. |
| Prompt | `briefing/prompt.py` + `prompts/system_prompt.md` | The system prompt is identical on every call, so it can be cached. The per-run inputs (`DISPATCH_TYPE`, `DATETIME`, feed items, market data, calendar, earlier dispatches) go in the user turn, and feed text is marked as untrusted data. |
| Research & writing | `briefing/llm.py` | Runs Claude Code headless (`claude -p`), signed in with your Pro subscription token; `ANTHROPIC_API_KEY` is stripped so a run can never bill an API account. `WebFetch` is locked by permission rules to the whitelisted domains (anything else is denied); `WebSearch` is told to use only Tier-1 results. Runs in an empty scratch folder so no project settings leak in. |
| Fallback (option C) | `briefing/digest.py` | If Claude Code fails, sends ranked Tier-1 headlines grouped by actor (Part 1) or by sector (Part 2), plus the market snapshot, clearly labelled as a digest. Digest items stay available for the next AI edition. |
| Quality gate | `briefing/postprocess.py`, `pipeline.py` | Strips `<thinking>` tags and preambles. Checks that every template section and the AM/PM label are present, and measures length the way Telegram does (UTF-16 units). Up to two tool-free rewrite passes (repair or compress); after that, a trim on a line boundary as a last resort. |
| Delivery | `briefing/telegram.py` | Converts `**bold**` / `*italic*` to Telegram HTML so special characters can't break the message. Falls back to plain text if Telegram rejects the HTML, and posts to several chats if configured. |
| Memory | `briefing/state.py` | Part 2 sees Part 1, and each edition sees the previous one (AM↔PM), so items aren't repeated. Items already used within 36h are skipped. |

## Coverage

The EU is the centre of gravity. The **US, China, Russia and BRICS+** each get their own coverage:

- **Part 1, Global Axis:** one bullet per actor (🇺🇸 🇨🇳 🇷🇺 🌍), each with a hard metric and the knock-on effect for Europe. A *Global Anchors* line in the Market Ledger adds DXY, USD/CNH, CSI 300 / Hang Seng, USD/RUB, and a BRICS+ currency or equity move.
- **Part 2:** US and Chinese tech and space moves are reported on their own merits.
- **Ingestion:** every feed item is tagged by actor (EU / US / CN / RU / BRICS). Each actor gets a guaranteed share of the items sent to the model (`region_quota` in `briefing/dispatch.py`, default 4), so heavy EU news can't crowd the others out.
- **Sources:** FT and Bloomberg regional feeds, plus official domains Claude can search: US Treasury/OFAC, Commerce, BIS, USTR, White House, DoD; China's State Council, PBoC, MOFCOM, NBS; Russia's CBR and Kremlin (quoted as official rhetoric only); the New Development Bank, RBI and Banco Central do Brasil.

## Schedule

| Target (UTC) | Job | Dispatches |
|---|---|---|
| ~05:30 | AM session | `AM_PART_1` → `AM_PART_2` |
| ~17:00 | PM session | `PM_PART_1` → `PM_PART_2` |

Each session runs Part 1 then Part 2 in the same job, in that order. You can change the times in `.github/workflows/dispatch.yml`.

## Setup

1. **Telegram:** create a bot with @BotFather and add it as an admin of your channel. Note the channel's `@name` or numeric id.
2. **Claude subscription token:** on your own computer, install Claude Code (`npm install -g @anthropic-ai/claude-code`), run `claude setup-token`, sign in with your Pro account and copy the long-lived token it prints.
3. **Repository secrets** (Settings → Secrets and variables → Actions): `CLAUDE_CODE_OAUTH_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS` (comma-separated).
   Optional repository **variables**: `BRIEFING_MODEL` (default `sonnet`) and `BRIEFING_EFFORT` (default `high`). Do **not** add an `ANTHROPIC_API_KEY`.
4. **Check it:** in Actions → *Intelligence Dispatch* → *Run workflow*, set `dispatch=PM` and untick `send`. Read the result in the uploaded archive artifact.
5. Keep `config/calendar.yaml` up to date with the week's known catalysts (ECB and Fed meetings, HICP, auctions).

### Running locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env && set -a && . ./.env && set +a

python -m briefing schedule                   # show the dispatch plan
python -m briefing check-feeds                # check every RSS feed
python -m briefing test-telegram              # check the bot and formatting
python -m briefing -v run PM --no-send        # generate both PM parts and print them
python -m briefing run AM_PART_1 --print-prompt --no-send
python -m pytest -q
```

To schedule with cron instead of Actions: `10 5 * * * cd /srv/gi && .venv/bin/python -m briefing run AM` (and `40 16` for PM).

## Cost and controls

- **No API billing.** Runs count against your Claude Pro usage limits, which are shared with your own use of Claude and Claude Code and reset every 5 hours. Two sessions a day, each with two research runs of up to 12 web searches, should fit on Pro with `sonnet`. If you use Claude heavily around 05:30 or 17:00 UTC, an edition may hit the limit and go out as a headline digest.
- `BRIEFING_MODEL=opus` gives stronger analysis but uses Pro limits much faster; `BRIEFING_EFFORT=medium` or `BRIEFING_WEB_SEARCH_MAX_USES=8` lower usage.
- GitHub Actions: about 10 minutes a day, well inside the free allowance.
- Every run's mode (`ai` or `digest`), any error, token usage and web tool calls are saved in `archive/<date>/<DISPATCH>.meta.json`.
- `--no-web` turns research off: Claude then writes only from the feeds and market snapshot, using less of your plan but losing verified hard numbers.
- The feed URLs in `config/sources.yaml` are publishers' public RSS endpoints, which change without notice. Run `check-feeds` after deploying and fix or remove any that fail. Reuters no longer publishes RSS, so its coverage comes from web search.
- The `claude setup-token` token is long-lived but can expire or be revoked. When it does, every edition becomes a digest (see `mode` in the metadata) until you generate a new one and update the secret.
