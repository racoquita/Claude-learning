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

from fred_client import FredError, get_series_observations

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


def load_json(path: pathlib.Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def main() -> int:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    observation_start = (
        dt.date.today() - dt.timedelta(days=365 * HISTORY_YEARS)
    ).isoformat()

    previous_latest = load_json(DATA_DIR / "latest.json", {})

    latest: dict = {}
    changes: list = []
    errors: list = []
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()

    for series_id, meta in SERIES.items():
        try:
            obs = get_series_observations(series_id, observation_start)
        except FredError as e:
            print(f"WARN: failed to fetch {series_id}: {e}", file=sys.stderr)
            errors.append({"series_id": series_id, "error": str(e)})
            continue

        if not obs:
            print(f"WARN: no observations returned for {series_id}", file=sys.stderr)
            continue

        (HISTORY_DIR / f"{series_id}.json").write_text(json.dumps(obs, indent=2))

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

    (DATA_DIR / "latest.json").write_text(json.dumps(latest, indent=2))
    (DATA_DIR / "changes.json").write_text(json.dumps(changes, indent=2))
    (DATA_DIR / "errors.json").write_text(json.dumps(errors, indent=2))

    print(f"Fetched {len(latest)}/{len(SERIES)} series. {len(changes)} new data point(s).")
    if changes:
        for c in changes:
            print(f"  NEW: {c['name']} ({c['series_id']}) -> {c['new_value']} on {c['new_date']}")

    return 1 if errors and not latest else 0


if __name__ == "__main__":
    raise SystemExit(main())
