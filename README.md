# Global Intelligence

An automated pipeline that writes executive intelligence briefings centred on the EU and posts them to Telegram. It sends **four dispatches a day** in two sessions (AM and PM, each Part 1 and Part 2). The writing is done by Claude with web research limited to Tier-1 sources. Every briefing must follow a fixed template and stay under 3,800 characters.

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
   (EUR/USD, Brent, TTF,        user turn     Claude + web_search  strip, validate     │
    VIX, indices, UST10Y)       (volatile)    + web_fetch limited  template, length    │
 config/calendar.yaml ────────►      ▲        to allowed_domains      │   ▲            │
   (next-48h catalysts)              │        system prompt cached    │   │ repair /   │
 state.py ───────────────────────────┘        pause_turn + refusal    │   │ compress   │
   (prior dispatches, seen items)             fallback handled        ▼   │ (≤2 passes)│
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
| Research & writing | `briefing/llm.py` | Uses `claude-opus-5` with adaptive thinking and effort `high`, and server-side refusal fallback (`fallbacks: "default"`). Paused turns are resumed. Only the final answer text is kept, not the model's narration between searches. |
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
2. **Repository secrets** (Settings → Secrets and variables → Actions): `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS` (comma-separated).
   Optional repository **variables**: `BRIEFING_MODEL` (default `claude-opus-5`) and `BRIEFING_EFFORT` (default `high`).
3. **Check it:** in Actions → *Intelligence Dispatch* → *Run workflow*, set `dispatch=PM` and untick `send`. Read the result in the uploaded archive artifact.
4. Keep `config/calendar.yaml` up to date with the week's known catalysts (ECB and Fed meetings, HICP, auctions).

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

- A dispatch is one research call (up to 15 web searches plus some fetches) and 0–2 short rewrite calls. Token usage and request IDs are saved in `archive/<date>/<DISPATCH>.meta.json`.
- `--no-web` turns research off: Claude then writes only from the feeds and market snapshot. Cheaper, but you lose the verified hard numbers.
- The feed URLs in `config/sources.yaml` are publishers' public RSS endpoints, which change without notice. Run `check-feeds` after deploying and fix or remove any that fail. Reuters no longer publishes RSS, so its coverage comes from web search.
