#!/usr/bin/env python3
"""Pull the FOMC-tracked indicators from FRED and cache them under data/.

Run with FRED_API_KEY set in the environment. Writes:
  data/history/<series_id>.json  - full observation history (ascending)
  data/latest.json               - latest observation per series + fetch time
  data/changes.json              - series whose latest data point changed
                                    since the previous run (hook point for
                                    notifications)
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

from fred_client import (FredError, get_series_observations, get_series_release_id,
                         get_upcoming_release_dates)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"

# The indicators FOMC statements and materials lean on most.
SERIES = {
    "CPIAUCSL": {
        "name": "Consumer Price Index",
        "units": "index (1982-84=100), SA",
        "frequency": "monthly",
    },
    "CPILFESL": {
        "name": "Core CPI (less food and energy)",
        "units": "index (1982-84=100), SA",
        "frequency": "monthly",
    },
    "UNRATE": {
        "name": "Unemployment Rate",
        "units": "percent, SA",
        "frequency": "monthly",
    },
    "PAYEMS": {
        "name": "Nonfarm Payrolls",
        "units": "thousands of persons, SA",
        "frequency": "monthly",
    },
    "GDPC1": {
        "name": "Real Gross Domestic Product",
        "units": "billions of chained 2017 dollars, SAAR",
        "frequency": "quarterly",
    },
    "DFEDTARU": {
        "name": "Fed Funds Target Rate (Upper Bound)",
        "units": "percent",
        "frequency": "daily (changes at FOMC decisions)",
    },
    "DFEDTARL": {
        "name": "Fed Funds Target Rate (Lower Bound)",
        "units": "percent",
        "frequency": "daily (changes at FOMC decisions)",
    },
}

HISTORY_YEARS = 12

# Releases shown in the "Next releases" panel, keyed by a series published in
# each. The release id is looked up from the series so it can't drift.
CALENDAR = {
    "cpi": {"label": "CPI", "series_id": "CPIAUCSL", "time_et": "8:30 AM"},
    "jobs": {"label": "Jobs report", "series_id": "PAYEMS", "time_et": "8:30 AM"},
    "gdp": {"label": "GDP", "series_id": "GDPC1", "time_et": "8:30 AM"},
}
CALENDAR_DATES_KEPT = 6


def fetch_calendar() -> None:
    """Refresh data/calendar.json; keep the previous entry for any release that fails."""
    path = DATA_DIR / "calendar.json"
    previous = load_json(path, {})
    today = dt.date.today().isoformat()
    out = {}
    for key, meta in CALENDAR.items():
        try:
            release_id, release_name = get_series_release_id(meta["series_id"])
            dates = get_upcoming_release_dates(release_id, today)[:CALENDAR_DATES_KEPT]
            out[key] = {**meta, "release_id": release_id, "release_name": release_name, "dates": dates}
        except FredError as e:
            print(f"WARN: failed to fetch release calendar for {key}: {e}", file=sys.stderr)
            if key in previous:
                out[key] = previous[key]
    if out != previous:  # only touch the file when the schedule changed
        path.write_text(json.dumps(out, indent=2))
    for key, entry in out.items():
        print(f"Calendar: {entry['label']} (release {entry.get('release_id')}) next {entry['dates'][:2]}")


def load_json(path: pathlib.Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def main() -> int:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    # Anchor to Jan 1 so the window only moves once a year; a rolling start
    # date dropped one daily observation per run and forced a commit every day.
    observation_start = dt.date(dt.date.today().year - HISTORY_YEARS, 1, 1).isoformat()

    previous_latest = load_json(DATA_DIR / "latest.json", {})

    latest: dict = {}
    changes: list = []
    errors: list = []
    data_changed = False
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()

    for series_id, meta in SERIES.items():
        try:
            obs = get_series_observations(series_id, observation_start)
        except FredError as e:
            print(f"WARN: failed to fetch {series_id}: {e}", file=sys.stderr)
            errors.append({"series_id": series_id, "error": str(e)})
            if series_id in previous_latest:
                latest[series_id] = previous_latest[series_id]  # keep last good entry
            continue

        if not obs:
            print(f"WARN: no observations returned for {series_id}", file=sys.stderr)
            continue

        hist_path = HISTORY_DIR / f"{series_id}.json"
        if load_json(hist_path, None) != obs:
            data_changed = True  # new release, revision, or new series
            hist_path.write_text(json.dumps(obs, indent=2))

        last = obs[-1]
        latest[series_id] = {
            **meta,
            "date": last["date"],
            "value": last["value"],
            "fetched_at": fetched_at,
        }

        prev = previous_latest.get(series_id)
        if prev and prev.get("date") != last["date"]:
            changes.append(
                {
                    "series_id": series_id,
                    "name": meta["name"],
                    "previous_date": prev.get("date"),
                    "previous_value": prev.get("value"),
                    "new_date": last["date"],
                    "new_value": last["value"],
                }
            )

    # Only rewrite latest.json (whose fetched_at changes every run) when the
    # data itself changed, so a no-op poll leaves the tree clean and the
    # workflow skips the commit.
    if data_changed or set(latest) != set(previous_latest):
        (DATA_DIR / "latest.json").write_text(json.dumps(latest, indent=2))
    (DATA_DIR / "changes.json").write_text(json.dumps(changes, indent=2))
    (DATA_DIR / "errors.json").write_text(json.dumps(errors, indent=2))

    fetch_calendar()

    print(f"Fetched {len(latest)}/{len(SERIES)} series. {len(changes)} new data point(s). "
          f"Data changed: {data_changed}.")
    if changes:
        for c in changes:
            print(f"  NEW: {c['name']} ({c['series_id']}) -> {c['new_value']} on {c['new_date']}")

    return 1 if errors and not latest else 0


if __name__ == "__main__":
    raise SystemExit(main())
