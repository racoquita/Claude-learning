#!/usr/bin/env python3
"""Render docs/index.html from the cached FRED data in data/.

Pure stdlib (no Jinja) — small enough to keep as one template string.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import string

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
DOCS_DIR = ROOT / "docs"


def load_json(path: pathlib.Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def history(series_id: str) -> list[dict]:
    return load_json(HISTORY_DIR / f"{series_id}.json", [])


def _month_index(d: str) -> int:
    date = dt.date.fromisoformat(d)
    return date.year * 12 + date.month - 1


def _lagged_pairs(series: list[dict], months: int):
    """Yield (prev, cur) where prev is exactly `months` calendar months before cur.

    Matches by date, not list position: FRED drops missing observations (e.g.
    October 2025, never collected during the funding lapse), so a positional
    lag would silently compare against the wrong month.
    """
    by_month = {_month_index(p["date"]): p for p in series}
    for cur in series:
        prev = by_month.get(_month_index(cur["date"]) - months)
        if prev is not None:
            yield prev, cur


def pct_change(series: list[dict], months: int) -> list[dict]:
    out = []
    for prev, cur in _lagged_pairs(series, months):
        if prev["value"] == 0:
            continue
        out.append({"date": cur["date"], "value": (cur["value"] / prev["value"] - 1) * 100})
    return out


def annualized_pct_change(series: list[dict], months: int) -> list[dict]:
    out = []
    for prev, cur in _lagged_pairs(series, months):
        if prev["value"] <= 0:
            continue
        rate = (cur["value"] / prev["value"]) ** (12 / months) - 1
        out.append({"date": cur["date"], "value": rate * 100})
    return out


def diff(series: list[dict], months: int = 1) -> list[dict]:
    return [{"date": cur["date"], "value": cur["value"] - prev["value"]}
            for prev, cur in _lagged_pairs(series, months)]


def prior(series: list[dict], months: int) -> dict | None:
    """The observation exactly `months` before the latest one, or None if missing."""
    target = _month_index(series[-1]["date"]) - months
    return next((p for p in reversed(series) if _month_index(p["date"]) == target), None)


def with_gaps(series: list[dict], step_months: int = 1) -> list[dict]:
    """Insert None values for missing periods so charts show a break, not a bridge."""
    out = []
    for p in series:
        if out:
            m = _month_index(out[-1]["date"]) + step_months
            while m < _month_index(p["date"]):
                out.append({"date": dt.date(m // 12, m % 12 + 1, 1).isoformat(), "value": None})
                m += step_months
        out.append(p)
    return out


def sparkline(series: list[dict], n: int = 12) -> list[float]:
    return [round(p["value"], 3) for p in series[-n:] if p["value"] is not None]


def fmt_date(d: str) -> str:
    return dt.date.fromisoformat(d).strftime("%b %Y")


def compact(n: float, decimals: int = 1) -> str:
    return f"{n:,.{decimals}f}"


def build_table_rows(series: list[dict], n: int = 24, unit: str = "") -> str:
    rows = []
    for p in series[-n:][::-1]:
        if p["value"] is None:
            rows.append(f"<tr><td>{fmt_date(p['date'])}</td><td>not published</td></tr>")
            continue
        rows.append(f"<tr><td>{fmt_date(p['date'])}</td><td>{compact(p['value'], 2)}{unit}</td></tr>")
    return "\n".join(rows)


def stat_tile(label: str, value: str, delta: str | None, delta_class: str, as_of: str, spark: list[float], spark_color: str,
              note: str | None = None) -> str:
    delta_html = f'<div class="tile-delta {delta_class}">{delta}</div>' if delta else ""
    points = spark or [0]
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1
    w, h, pad = 96, 28, 3
    step = (w - 2 * pad) / max(len(points) - 1, 1)
    coords = []
    for i, v in enumerate(points):
        x = pad + i * step
        y = pad + (h - 2 * pad) * (1 - (v - lo) / span)
        coords.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(coords)
    last = coords[-1].split(",")
    spark_svg = (
        f'<svg class="sparkline" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline points="{polyline}" fill="none" stroke="{spark_color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last[0]}" cy="{last[1]}" r="2.5" fill="{spark_color}"/>'
        f"</svg>"
    )
    return f"""
    <div class="tile">
      <div class="tile-label">{label}</div>
      <div class="tile-value">{value}</div>
      {delta_html}
      {spark_svg}
      <div class="tile-asof">as of {as_of}</div>
      {f'<div class="tile-note">{note}</div>' if note else ""}
    </div>"""


def chart_card(chart_id: str, title: str, subtitle: str, series: list[dict], color_var: str,
               kind: str, unit: str, table_unit: str, diverging: bool = False) -> tuple[str, dict]:
    labels = [fmt_date(p["date"]) for p in series]
    values = [None if p["value"] is None else round(p["value"], 3) for p in series]
    table_rows = build_table_rows(series, unit=table_unit)
    chart_config = {
        "id": chart_id,
        "kind": kind,
        "labels": labels,
        "values": values,
        "colorVar": color_var,
        "diverging": diverging,
        "unit": unit,
    }
    html = f"""
    <figure class="chart-card">
      <figcaption>
        <h3>{title}</h3>
        <p class="chart-subtitle">{subtitle}</p>
      </figcaption>
      <div class="chart-wrap"><canvas id="{chart_id}"></canvas></div>
      <details class="table-toggle">
        <summary>View as table</summary>
        <div class="table-scroll">
          <table>
            <thead><tr><th>Period</th><th>Value</th></tr></thead>
            <tbody>{table_rows}</tbody>
          </table>
        </div>
      </details>
    </figure>"""
    return html, chart_config


TEMPLATE = string.Template(r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FOMC Economic Dashboard</title>
<meta name="description" content="Auto-updating dashboard of the indicators the FOMC watches most: CPI, core CPI, unemployment, jobs added, GDP growth, and the Fed funds target rate.">
<script src="vendor/chart.umd.js"></script>
<style>
:root {
  color-scheme: light;
  --surface-1: #fcfcfb;
  --page: #f9f9f7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --text-muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --delta-good: #006300;
  --warn: #a35a00;
  --delta-bad: #d03b3b;
  --series-cpi: #2a78d6;
  --series-core-cpi: #c2477d;
  --series-unemployment: #eb6834;
  --series-gdp: #1baf7a;
  --series-fedfunds: #4a3aa7;
  --series-jobs-pos: #2a78d6;
  --series-jobs-neg: #e34948;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --page: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --delta-good: #0ca30c;
    --warn: #e8a33d;
    --delta-bad: #d03b3b;
    --series-cpi: #3987e5;
    --series-core-cpi: #e0679c;
    --series-unemployment: #d95926;
    --series-gdp: #199e70;
    --series-fedfunds: #9085e9;
    --series-jobs-pos: #3987e5;
    --series-jobs-neg: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19;
  --page: #0d0d0d;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted: #898781;
  --grid: #2c2c2a;
  --axis: #383835;
  --border: rgba(255,255,255,0.10);
  --delta-good: #0ca30c;
  --warn: #e8a33d;
  --delta-bad: #d03b3b;
  --series-cpi: #3987e5;
  --series-core-cpi: #e0679c;
  --series-unemployment: #d95926;
  --series-gdp: #199e70;
  --series-fedfunds: #9085e9;
  --series-jobs-pos: #3987e5;
  --series-jobs-neg: #e66767;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1120px; margin: 0 auto; padding: 24px 20px 64px; }
header.page-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 16px; flex-wrap: wrap; margin-bottom: 16px;
}
header.page-header > div { flex: 1 1 320px; min-width: 0; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
.subtitle { color: var(--text-secondary); margin: 0; font-size: 0.95rem; }
.meta { color: var(--text-muted); font-size: 0.82rem; margin-top: 6px; }
.freshness {
  display: inline-flex; align-items: center; gap: 12px; flex-wrap: wrap;
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
  padding: 10px 16px; margin: 0 0 20px;
}
.freshness-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--delta-good); flex: none; }
.freshness.stale .freshness-dot { background: var(--warn); }
.freshness-label { font-size: 0.8rem; color: var(--text-secondary); }
.freshness-time { font-size: 1.15rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.freshness-ago { font-size: 0.9rem; color: var(--text-secondary); }
.freshness.stale .freshness-ago { color: var(--warn); font-weight: 600; }
#theme-toggle {
  border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
  border-radius: 8px; padding: 8px 12px; font-size: 0.85rem; cursor: pointer;
}
.tiles {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
  gap: 12px; margin-bottom: 28px;
}
.tile {
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
  padding: 14px 16px;
}
.tile-label { font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 6px; }
.tile-value { font-size: 1.6rem; font-weight: 600; }
.tile-delta { font-size: 0.82rem; margin-top: 2px; }
.tile-delta.good { color: var(--delta-good); }
.tile-delta.bad { color: var(--delta-bad); }
.tile-delta.neutral { color: var(--text-secondary); }
.sparkline { width: 100%; max-width: 160px; height: 28px; margin-top: 8px; display: block; }
.tile-asof { font-size: 0.72rem; color: var(--text-muted); margin-top: 6px; }
.tile-note { font-size: 0.72rem; color: var(--text-secondary); margin-top: 4px; line-height: 1.4; }
.charts {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr)); gap: 16px;
}
.chart-card {
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px; margin: 0;
}
.chart-card h3 { margin: 0 0 2px; font-size: 1rem; }
.chart-subtitle { margin: 0 0 12px; color: var(--text-secondary); font-size: 0.82rem; }
.chart-wrap { height: 220px; }
.table-toggle { margin-top: 10px; }
.table-toggle summary { cursor: pointer; font-size: 0.8rem; color: var(--text-secondary); }
.table-scroll { overflow-x: auto; margin-top: 8px; max-height: 220px; overflow-y: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
th { color: var(--text-secondary); font-weight: 500; }
footer { margin-top: 32px; color: var(--text-muted); font-size: 0.78rem; line-height: 1.6; }
footer a { color: inherit; }
.errors { background: var(--surface-1); border: 1px solid var(--delta-bad); border-radius: 12px; padding: 12px 16px; margin-bottom: 20px; font-size: 0.85rem; color: var(--delta-bad); }
</style>
</head>
<body>
<div class="wrap">
  <header class="page-header">
    <div>
      <h1>FOMC Economic Dashboard</h1>
      <p class="subtitle">The indicators behind every Fed decision: inflation, employment, growth, and the policy rate.</p>
      <p class="meta">Data from FRED (Federal Reserve Bank of St. Louis), sourced from BLS, BEA, and the Federal Reserve. Checked for new releases three times each weekday.</p>
    </div>
    <button id="theme-toggle" type="button" aria-label="Toggle dark mode">&#9680; Theme</button>
  </header>

  <div class="freshness" id="freshness" data-ts="$LAST_REFRESHED_ISO" role="status">
    <span class="freshness-dot" aria-hidden="true"></span>
    <span class="freshness-label">Last refreshed</span>
    <time class="freshness-time" id="freshness-time" datetime="$LAST_REFRESHED_ISO">$LAST_REFRESHED</time>
    <span class="freshness-ago" id="freshness-ago"></span>
  </div>

  $ERROR_BANNER

  <section class="tiles">
    $TILES
  </section>

  <section class="charts">
    $CHARTS
  </section>

  <footer>
    <p>Series: CPI (CPIAUCSL, YoY %), Core CPI excl. food &amp; energy (CPILFESL, YoY %), Unemployment Rate (UNRATE), Nonfarm Payrolls change (PAYEMS, jobs added/month),
    Real GDP (GDPC1, QoQ annualized %), Fed Funds Target Rate upper bound (DFEDTARU). All via the
    <a href="https://fred.stlouisfed.org/" target="_blank" rel="noopener">FRED API</a>.</p>
    <p>This page is rebuilt automatically by a scheduled GitHub Actions workflow. See the repo README for setup and how to wire up push/email notifications.</p>
  </footer>
</div>

<script>
const CHARTS = $CHARTS_JSON;

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const bigint = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
  const r = (bigint >> 16) & 255, g = (bigint >> 8) & 255, b = bigint & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const instances = [];

function renderCharts() {
  const gridColor = cssVar('--grid');
  const axisColor = cssVar('--axis');
  const tickColor = cssVar('--text-muted');
  const surface = cssVar('--surface-1');
  const textPrimary = cssVar('--text-primary');

  instances.forEach(c => c.destroy());
  instances.length = 0;

  CHARTS.forEach(cfg => {
    const ctx = document.getElementById(cfg.id).getContext('2d');
    const color = cssVar(cfg.colorVar);
    const common = {
      scales: {
        x: { grid: { display: false }, ticks: { color: tickColor, maxRotation: 0, autoSkip: true, maxTicksLimit: 7 }, border: { color: axisColor } },
        y: { grid: { color: gridColor }, ticks: { color: tickColor }, border: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: surface, titleColor: textPrimary, bodyColor: textPrimary,
          borderColor: axisColor, borderWidth: 1, padding: 10, displayColors: false,
          callbacks: { label: (item) => `${item.formattedValue}${cfg.unit}` },
        },
      },
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
    };

    if (cfg.kind === 'bar') {
      const posColor = cssVar('--series-jobs-pos');
      const negColor = cssVar('--series-jobs-neg');
      instances.push(new Chart(ctx, {
        type: 'bar',
        data: {
          labels: cfg.labels,
          datasets: [{
            data: cfg.values,
            backgroundColor: cfg.values.map(v => v >= 0 ? posColor : negColor),
            borderRadius: 4, borderSkipped: false, maxBarThickness: 18,
          }],
        },
        options: common,
      }));
    } else {
      const stepped = cfg.kind === 'step';
      instances.push(new Chart(ctx, {
        type: 'line',
        data: {
          labels: cfg.labels,
          datasets: [{
            data: cfg.values,
            borderColor: color,
            backgroundColor: hexToRgba(color.startsWith('#') ? color : '#2a78d6', 0.10),
            fill: true, borderWidth: 2, pointRadius: 0,
            pointHoverRadius: 4, pointHoverBackgroundColor: color,
            pointHoverBorderColor: surface, pointHoverBorderWidth: 2,
            tension: stepped ? 0 : 0.15, stepped: stepped,
          }],
        },
        options: common,
      }));
    }
  });
}

renderCharts();

// Show the refresh time in the viewer's own time zone, with its age.
(function () {
  const box = document.getElementById('freshness');
  const ts = Date.parse(box.dataset.ts);
  if (isNaN(ts)) return;
  document.getElementById('freshness-time').textContent = new Date(ts).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  });
  const ago = document.getElementById('freshness-ago');
  function update() {
    const mins = Math.max(0, Math.round((Date.now() - ts) / 60000));
    const text = mins < 60 ? `${mins} min ago`
      : mins < 48 * 60 ? `${Math.round(mins / 60)} hours ago`
      : `${Math.round(mins / 1440)} days ago`;
    const stale = mins > 3 * 1440;  // longer than a weekend: the refresh job is likely stuck
    box.classList.toggle('stale', stale);
    ago.textContent = stale ? `${text} · may be out of date` : text;
  }
  update();
  setInterval(update, 60000);
})();

const toggle = document.getElementById('theme-toggle');
const stored = localStorage.getItem('fomc-dashboard-theme');
if (stored) document.documentElement.setAttribute('data-theme', stored);
toggle.addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme')
    || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('fomc-dashboard-theme', next);
  renderCharts();
});
</script>
</body>
</html>
""")


def main() -> int:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    latest = load_json(DATA_DIR / "latest.json", {})
    errors = load_json(DATA_DIR / "errors.json", [])

    cpi_hist = history("CPIAUCSL")
    core_cpi_hist = history("CPILFESL")
    unrate_hist = history("UNRATE")
    payems_hist = history("PAYEMS")
    gdp_hist = history("GDPC1")
    fedfunds_hist = history("DFEDTARU")

    cpi_yoy = pct_change(cpi_hist, 12)
    core_cpi_yoy = pct_change(core_cpi_hist, 12)
    jobs_added = diff(payems_hist, 1)
    gdp_growth = annualized_pct_change(gdp_hist, 3)

    if not (cpi_yoy and unrate_hist and jobs_added and gdp_growth and fedfunds_hist):
        missing = [n for n, s in [("CPI", cpi_yoy), ("unemployment", unrate_hist),
                                   ("jobs", jobs_added), ("GDP", gdp_growth),
                                   ("fed funds", fedfunds_hist)] if not s]
        print(f"Not enough cached data to build dashboard yet (missing: {', '.join(missing)}). "
              f"Run scripts/fetch_data.py with FRED_API_KEY set first.")
        return 1

    def delta_class(cur, prev, higher_is_good):
        if round(cur, 1) == round(prev, 1):
            return "neutral"
        if higher_is_good:
            return "good" if cur > prev else "bad"
        return "good" if cur < prev else "bad"

    def rate_tile(label, series, months, period, higher_is_good, color, raw_hist=None):
        cur = series[-1]["value"]
        prev = prior(series, months)
        delta, cls = None, "neutral"
        if prev is not None:
            delta = f"{cur - prev['value']:+.1f} pts vs {period}"
            cls = delta_class(cur, prev["value"], higher_is_good)
        note = None
        # A newer raw observation exists but its YoY base month was never published.
        if raw_hist and raw_hist[-1]["date"] > series[-1]["date"]:
            newest = raw_hist[-1]["date"]
            base = dt.date.fromisoformat(newest).replace(year=int(newest[:4]) - 1).isoformat()
            note = (f"{fmt_date(newest)} 12-month change not published: "
                    f"no {fmt_date(base)} data (2025 funding lapse).")
        return stat_tile(label, f"{cur:.1f}%", delta, cls, fmt_date(series[-1]["date"]),
                         sparkline(series), color, note)

    tiles = [rate_tile("CPI (YoY)", cpi_yoy, 1, "last month", False, "#2a78d6", cpi_hist)]

    # Core CPI is optional so the page still builds before its first fetch.
    if core_cpi_yoy:
        tiles.append(rate_tile("Core CPI (YoY)", core_cpi_yoy, 1, "last month", False, "#c2477d", core_cpi_hist))

    tiles.append(rate_tile("Unemployment Rate", unrate_hist, 1, "last month", False, "#eb6834"))

    jobs_cur = jobs_added[-1]["value"]
    tiles.append(stat_tile(
        "Jobs Added (monthly)", f"{jobs_cur:+,.0f}K",
        None, "neutral",
        fmt_date(jobs_added[-1]["date"]), sparkline(jobs_added), "#2a78d6"))

    tiles.append(rate_tile("GDP Growth (QoQ ann.)", gdp_growth, 3, "prior quarter", True, "#1baf7a"))

    ff_upper = fedfunds_hist[-1]["value"]
    ff_lower_hist = history("DFEDTARL")
    ff_lower = ff_lower_hist[-1]["value"] if ff_lower_hist else None
    ff_label = f"{ff_lower:.2f}–{ff_upper:.2f}%" if ff_lower is not None else f"{ff_upper:.2f}%"
    tiles.append(stat_tile(
        "Fed Funds Target Range", ff_label,
        None, "neutral",
        fmt_date(fedfunds_hist[-1]["date"]), sparkline(fedfunds_hist), "#4a3aa7"))

    chart_htmls = []
    chart_configs = []

    cards = [
        chart_card("chart-cpi", "CPI, Year-over-Year", "Headline inflation rate, monthly", with_gaps(cpi_yoy),
                   "--series-cpi", "line", "%", "%"),
    ]
    if core_cpi_yoy:
        cards.append(chart_card("chart-core-cpi", "Core CPI, Year-over-Year",
                                "Inflation excluding food and energy, monthly", with_gaps(core_cpi_yoy),
                                "--series-core-cpi", "line", "%", "%"))
    cards += [
        chart_card("chart-unrate", "Unemployment Rate", "Share of labor force unemployed, monthly", with_gaps(unrate_hist),
                   "--series-unemployment", "line", "%", "%"),
        chart_card("chart-jobs", "Jobs Added / Lost", "Change in nonfarm payrolls, thousands, monthly", with_gaps(jobs_added),
                   "--series-jobs-pos", "bar", "K", "K", diverging=True),
        chart_card("chart-gdp", "GDP Growth", "Real GDP, quarter-over-quarter annualized, quarterly", with_gaps(gdp_growth, 3),
                   "--series-gdp", "line", "%", "%"),
        chart_card("chart-fedfunds", "Fed Funds Target Rate", "Upper bound of the FOMC's target range, daily",
                   fedfunds_hist, "--series-fedfunds", "step", "%", "%"),
    ]

    for html, cfg in cards:
        chart_htmls.append(html)
        chart_configs.append(cfg)

    error_banner = ""
    if errors:
        names = ", ".join(e["series_id"] for e in errors)
        error_banner = f'<div class="errors">Some series failed to refresh this run and may show stale data: {names}.</div>'

    last_refreshed, last_refreshed_iso = "never", ""
    if latest:
        any_fetch = next(iter(latest.values())).get("fetched_at")
        if any_fetch:
            fetched = dt.datetime.fromisoformat(any_fetch)
            last_refreshed = fetched.strftime("%b %-d, %Y, %H:%M UTC")  # no-JS fallback
            last_refreshed_iso = fetched.isoformat()

    html = TEMPLATE.safe_substitute(
        LAST_REFRESHED=last_refreshed,
        LAST_REFRESHED_ISO=last_refreshed_iso,
        ERROR_BANNER=error_banner,
        TILES="\n".join(tiles),
        CHARTS="\n".join(chart_htmls),
        CHARTS_JSON=json.dumps(chart_configs),
    )

    (DOCS_DIR / "index.html").write_text(html)
    (DOCS_DIR / ".nojekyll").write_text("")
    print(f"Wrote {DOCS_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
