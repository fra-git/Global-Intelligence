# Global Intelligence

An automated pipeline that researches and writes a long-form **world intelligence report** and delivers it to Telegram as a **PDF**, with a short summary message. The goal is simple: know what is happening around you, in Italy, across Europe and in every major region and power of the world, across geopolitics, defence, cyber, technology and AI, space, the economy, finance and energy.

The research and writing are done by **Claude Code running on a Claude Pro subscription** (no API billing), using reputable sources only. If Claude is unavailable for part of a run (plan limit, expired token, outage), the affected sections fall back to **headline digests** from the news feeds, and the report still goes out.

## Editions

| When (Italy time) | Edition | Length | Telegram |
|---|---|---|---|
| **05:50**, Monday–Saturday | **Daily Intelligence Report** | full report, ~20–30 pages | summary of the top stories + PDF |
| **05:50**, Sunday | **Weekly Deep-Dive** | ~30–40 pages | the week in one page + PDF |
| **20:50**, every day | **Evening Update** | what changed since the morning, ~5 pages | what changed today + PDF |

### What's in the daily report

1. **At a Glance:** the 8–10 most important developments, one line each.
2. **Markets Dashboard:** indices, rates, currencies and commodities for Europe, the Americas and Asia, with daily and weekly moves.
3. **Europe & Italy:** Italy (politics and economy), the European Union, and a country-by-country roundup of the rest of Europe.
4. **Great Powers:** the United States, China, Russia & Ukraine.
5. **World Regions:** the Middle East & Gulf, the Indo-Pacific, BRICS+ & the Global South, Africa, Latin America.
6. **Security, Technology & Space:** defence and security, cyber and information warfare, technology and AI, space.
7. **Economy, Markets & Energy:** the global economy and central banks, markets and finance, trade, tariffs and sanctions, energy and critical minerals.
8. **Outlook:** scenarios for the 3 biggest stories, a 7-day "What to Watch" calendar, and a glossary.

Every story follows the same pattern: **what happened → why it matters → what it means for Europe & Italy → what to watch**, with source links. Complex stories get a **Background** box explaining the context.

The **Sunday Weekly Deep-Dive** covers the same sections for the whole week, and adds **Trends of the Week**, a long **Deep Dive** essay on the week's most consequential theme, a **Scenario Scorecard** (which of the week's scenarios played out), and **Week Ahead**.

## Architecture

```
  cron-job.org (exact time) ──┐   GitHub cron (backup, can run late)
                              ▼          │
                 GitHub Actions: Intelligence Dispatch ◄─┘
                              │
 config/sources.yaml ──► ingest.py ── 59 feeds fetched in parallel, windowed, de-duplicated,
                              │       ranked, tagged by region (IT, EU, US, CN, RU, ME, IP, AF,
                              │       LA, BRICS) and topic (defence, cyber, tech, space, econ, energy)
 markets.py ──────────────────┤
                              ▼
        ┌──────── research desks, side by side (one `claude -p` run each) ────────┐
        │ Europe & Italy │ Great Powers │ World Regions │ Security/Tech/Space │ Economy │
        └─────────────── WebSearch + WebFetch on whitelisted domains ─────────────┘
                              │   (failed desk → headline digest for its sections)
                              ▼
                 editor run: front page, scenarios, what to watch, glossary
                              │
                 report.py: markdown → HTML → PDF (WeasyPrint)
                              │
                 telegram.py: summary message + PDF document
                              │
         archive/YYYY-MM-DD/<EDITION>.md / .pdf / .meta.json · state/state.json
```

| Stage | Module | What it guarantees |
|---|---|---|
| Editions and sections | `briefing/dispatch.py` | Defines every section, which desk writes it, its guidance and target length. Edit here to add, remove or resize sections. |
| Source registry | `config/sources.yaml` | 59 RSS feeds (Tier-1 wires and papers, Italian outlets, regional, defence, cyber, tech, space, official and think-tank). Web fetches are hard-limited to the whitelisted domains. |
| Ingestion | `briefing/ingest.py` | Each desk gets the items matching its regions/topics, with a guaranteed share per region so busy stories can't crowd out quieter places like Africa or Latin America. A dead feed is skipped. |
| Research & writing | `briefing/llm.py`, `briefing/prompt.py`, `prompts/system_prompt.md` | Each desk runs Claude Code headless on your Pro subscription (`ANTHROPIC_API_KEY` is stripped), verifies facts with web research, and writes its sections. Feed text is marked as untrusted data. |
| Quality gate | `briefing/postprocess.py`, `briefing/pipeline.py` | Strips non-report text, checks every section is present (one repair pass if not), and fills any still-missing section with a labelled headline digest. |
| PDF | `briefing/report.py` | Cover with At a Glance, contents with page numbers, part banners, explainer boxes, market tables. Model output can't inject HTML, only http(s) links survive, and the renderer fetches nothing from the internet. |
| Delivery | `briefing/telegram.py` | Summary message (Telegram HTML, plain-text fallback), then the PDF. |
| Memory | `briefing/state.py` | Each edition sees what the previous one covered and doesn't repeat it; the evening skips items the morning used; the weekly gets the week's front pages and scenarios; a session is never sent twice. |

## Exact timing (cron-job.org)

GitHub's built-in scheduler is "best effort": under load it starts jobs late, sometimes by hours (this is why editions arrived around 12:45 and midnight). The fix is a free external scheduler that starts the workflow at the exact minute. GitHub's own schedule stays as a backup: if it fires after the external trigger already delivered that session, it sends nothing.

**1. Create a GitHub token that can start the workflow (5 min)**

1. On GitHub: your avatar → **Settings** → **Developer settings** (bottom left) → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. **Token name:** `cron-job trigger`. **Expiration:** the longest allowed (add a calendar reminder to renew it).
3. **Repository access:** *Only select repositories* → `fra-git/Global-Intelligence`.
4. **Permissions** → **Repository permissions** → **Actions:** *Read and write*. Leave everything else alone.
5. **Generate token** and copy it (it starts with `github_pat_`). You will paste it into cron-job.org; don't put it anywhere else.

**2. Create the two scheduled calls on cron-job.org (10 min)**

1. Sign up for free at **cron-job.org** and confirm your email.
2. **Settings** (top right) → set your **time zone** to `Europe/Rome`. This handles summer/winter time automatically.
3. **Cronjobs** → **Create cronjob**:
   - **Title:** `Global Intelligence AM`
   - **URL:** `https://api.github.com/repos/fra-git/Global-Intelligence/actions/workflows/dispatch.yml/dispatches`
   - **Execution schedule:** *Every day* at **05:50**
   - Open the **Advanced** tab:
     - **Request method:** `POST`
     - **Headers** (add four):
       - `Accept` = `application/vnd.github+json`
       - `Authorization` = `Bearer github_pat_...` (your token)
       - `X-GitHub-Api-Version` = `2022-11-28`
       - `Content-Type` = `application/json`
     - **Request body:** `{"ref":"main","inputs":{"edition":"AM"}}`
   - **Create**.
4. Create a second cronjob the same way: title `Global Intelligence PM`, **20:50**, body `{"ref":"main","inputs":{"edition":"PM"}}`.
5. Test: open a cronjob → **Test run**. A response of **204** means it worked, and a new run appears within seconds under **Actions → Intelligence Dispatch** on GitHub. (A test run really sends that session. If it already went out today, it's skipped.)

## Setup

1. **Telegram:** create a bot with @BotFather and add it as an admin of your channel (or start a chat with it). Note the channel's `@name` or the numeric chat id.
2. **Claude subscription token:** on your own computer, install Claude Code (`npm install -g @anthropic-ai/claude-code`), run `claude setup-token`, sign in with your Pro account and copy the long-lived token.
3. **Repository secrets** (Settings → Secrets and variables → Actions): `CLAUDE_CODE_OAUTH_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS` (comma-separated). Do **not** add an `ANTHROPIC_API_KEY`.
4. **Optional repository variables:** `BRIEFING_MODEL` (default `sonnet`), `BRIEFING_EFFORT` (default `high`), `BRIEFING_PARALLEL_DESKS` (default `3`), `BRIEFING_SEARCH_SCALE` (default `1`).
5. **Exact timing:** set up cron-job.org as described above.
6. **Test:** Actions → *Intelligence Dispatch* → *Run workflow*. Pick `edition=EVENING` for a quick run (~10 min) or `DAILY` for the full report (~30–45 min). Tick **force** if that session was already sent today. The PDF is also saved as a downloadable artifact of the run.

### Running locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt     # WeasyPrint needs Pango: apt install libpango-1.0-0 libpangoft2-1.0-0
cp .env.example .env && set -a && . ./.env && set +a

python -m briefing schedule                   # show the schedule and editions
python -m briefing check-feeds                # check every RSS feed
python -m briefing test-telegram              # send a test message and a test PDF
python -m briefing -v run EVENING --no-send   # generate the evening update into archive/
python -m briefing -v run DAILY --no-send     # generate the full daily report
python -m pytest -q
```

## Claude Pro usage and controls

- **No API billing.** Runs count against your Claude Pro usage limits, which are shared with your own use of Claude and reset every 5 hours. The runs start right at your 05:50 and 20:50 resets.
- **The daily report is heavy:** 5 research desks with about 10 web searches each, plus an editor run, can use a large part of a 5-hour window. You'll have less Claude left for your own work right after 05:50 than after 20:50 (the evening update is a single run). If a desk hits the limit, its sections go out as headline digests and the rest of the report is still complete; the run's metadata shows which.
- **To use less:** set `BRIEFING_SEARCH_SCALE=0.5` (half the web searches) or `BRIEFING_EFFORT=medium`, or shorten sections by lowering their `words` in `briefing/dispatch.py`. `BRIEFING_MODEL=opus` writes better analysis but uses limits much faster.
- **Rate limits:** if desks fail when run side by side, set `BRIEFING_PARALLEL_DESKS=1` (slower but gentler).
- **GitHub Actions:** the repository is public, so Actions minutes are free and unlimited. Run artifacts (including the PDFs) are visible to anyone who can see the repository.
- Each run's mode (`ai`, `partial` or `digest`), per-desk errors, word and page counts, and web lookups are saved in `archive/<date>/<EDITION>.meta.json`.
- Feed URLs change without notice. Run `check-feeds` and fix or remove any that fail. The `claude setup-token` token is long-lived but can expire; when it does, every section becomes a headline digest until you generate a new one and update the secret.
