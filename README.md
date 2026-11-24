# FOMC Economic Dashboard

An auto-updating dashboard of the indicators the Federal Reserve watches most:

- **CPI** (year-over-year inflation)
- **Core CPI** (year-over-year, excluding food and energy)
- **Unemployment rate**
- **Jobs added/lost** (monthly change in nonfarm payrolls)
- **GDP growth** (quarter-over-quarter, annualized)
- **Fed funds target rate** (the FOMC's policy rate)

All data comes directly from [FRED](https://fred.stlouisfed.org/) (Federal Reserve
Bank of St. Louis), which republishes the official series from the BLS, BEA, and
the Federal Reserve itself — no scraping, no secondary sources.

A scheduled GitHub Actions workflow polls FRED on a schedule, and rebuilds and
republishes the dashboard whenever new data appears. The published site is a
static page under `docs/`, served by GitHub Pages.

## One-time setup

1. **Get a free FRED API key**: https://fred.stlouisfed.org/docs/api/api_key.html
   (instant, no approval wait).
2. **Add it as a repo secret**: repo Settings → Secrets and variables → Actions →
   New repository secret → name it `FRED_API_KEY`, paste the key.
3. **Enable GitHub Pages**: repo Settings → Pages → Build and deployment →
   Source: "Deploy from a branch" → Branch: the repo's default branch
   (currently `claude/fomc-economic-dashboard-5j63c7`), folder: `/docs` → Save.
   Scheduled workflows also only run on the default branch.
4. **Run the workflow once manually** to populate real data: Actions tab →
   "Update economic dashboard" → Run workflow. After it finishes (~30s), your
   Pages URL (shown in Settings → Pages) will show the live dashboard instead
   of the placeholder page.

That's it — from then on it refreshes itself.

## How it refreshes

`.github/workflows/update-dashboard.yml` checks three times each weekday:
14:07 UTC (after the 8:30am ET BLS/BEA releases), 19:37 UTC (after the 2pm ET
FOMC announcement) and 23:07 UTC (late catch-up). GitHub's scheduler is
best-effort and can delay or drop runs; runs that find no new data exit
without committing. You can also
trigger it manually from the Actions tab any time.

Each run:

1. `scripts/fetch_data.py` pulls the latest observations for each series from
   FRED and caches them under `data/`.
2. `scripts/build_dashboard.py` computes the derived metrics (CPI and core CPI YoY%, jobs
   added, GDP annualized growth) and regenerates `docs/index.html`.
3. If the data changed (a new release or a revision), the workflow commits and pushes — which republishes
   the GitHub Pages site automatically.

Data series tracked (FRED codes): `CPIAUCSL`, `CPILFESL`, `UNRATE`, `PAYEMS`, `GDPC1`,
`DFEDTARU`/`DFEDTARL`. See `scripts/fetch_data.py` for details.

## Notifications (not wired up yet)

You asked to skip notifications for the first version, but the pipeline
already has the hook for it: every run writes `data/changes.json`, a list of
any series whose latest data point changed since the previous run — i.e.
exactly the "new release just dropped" event. It's empty most runs and
populated only when something new comes out.

To add notifications later, add a step at the end of the workflow (after the
build step) that reads `data/changes.json` and, if non-empty, sends a message.
The easiest options, roughly in order of setup effort:

- **[ntfy.sh](https://ntfy.sh)** — free, no account: pick a private topic name
  and `curl -d "$(cat data/changes.json)" https://ntfy.sh/your-topic-name` from
  the workflow. Install the ntfy app to get it as a push notification.
- **Slack/Discord webhook** — `curl -X POST -H 'Content-type: application/json'
  --data '{"text": "..."}' "$SLACK_WEBHOOK_URL"`, with the webhook URL as a repo
  secret.
- **Email** — via an Action like `dawidd6/action-send-mail` using a Gmail app
  password stored as a secret.

Ask for this to be wired up whenever you're ready and specify which channel.

## Local development

No external dependencies — everything runs on the Python 3 standard library.

```bash
export FRED_API_KEY=your_key_here
python3 scripts/fetch_data.py     # populates data/
python3 scripts/build_dashboard.py  # writes docs/index.html
python3 -m http.server 8000 --directory docs  # preview locally
```

## Repo layout

```
scripts/fred_client.py       Minimal FRED API client (stdlib urllib only)
scripts/fetch_data.py        Pulls series, caches history + latest + diffs
scripts/build_dashboard.py   Renders docs/index.html from cached data
data/history/<series>.json   Full observation history per series
data/latest.json             Latest observation per series + fetch timestamp
data/changes.json            Series that changed on the most recent run
data/calendar.json           Upcoming CPI/jobs/GDP release dates (FRED release calendar)
data/fomc_dates.json         FOMC decision dates, kept by hand (update yearly from federalreserve.gov)
docs/index.html              The published dashboard (generated)
docs/vendor/chart.umd.js     Vendored Chart.js (no external CDN dependency)
.github/workflows/           The scheduled refresh job
```
