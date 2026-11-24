"""Minimal client for the FRED (Federal Reserve Economic Data) API.

Docs: https://fred.stlouisfed.org/docs/api/fred/
Requires a free API key: https://fred.stlouisfed.org/docs/api/api_key.html
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
import json

FRED_BASE_URL = "https://api.stlouisfed.org/fred"


class FredError(RuntimeError):
    pass


def _get(path: str, params: dict) -> dict:
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise FredError(
            "FRED_API_KEY environment variable is not set. "
            "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )
    query = {**params, "api_key": api_key, "file_type": "json"}
    url = f"{FRED_BASE_URL}/{path}?{urllib.parse.urlencode(query)}"

    last_err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise FredError(f"FRED API HTTP {e.code} for {path}: {body}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise FredError(f"FRED API request failed after retries: {last_err}")


def get_series_observations(series_id: str, observation_start: str) -> list[dict]:
    """Return [{date, value}] ascending, dropping FRED's '.' missing-value marker."""
    data = _get(
        "series/observations",
        {
            "series_id": series_id,
            "observation_start": observation_start,
            "sort_order": "asc",
        },
    )
    out = []
    for obs in data.get("observations", []):
        if obs["value"] == ".":
            continue
        out.append({"date": obs["date"], "value": float(obs["value"])})
    return out


def get_series_info(series_id: str) -> dict:
    data = _get("series", {"series_id": series_id})
    seriess = data.get("seriess") or []
    return seriess[0] if seriess else {}


def get_series_release_id(series_id: str) -> tuple[int, str]:
    """The FRED release (id, name) a series is published in, e.g. CPIAUCSL -> Consumer Price Index."""
    data = _get("series/release", {"series_id": series_id})
    releases = data.get("releases") or []
    if not releases:
        raise FredError(f"No release found for series {series_id}")
    return int(releases[0]["id"]), releases[0]["name"]


def get_upcoming_release_dates(release_id: int, start: str) -> list[str]:
    """Scheduled release dates on or after `start` (YYYY-MM-DD), ascending.

    include_release_dates_with_no_data=true is what makes FRED return
    future dates; without it only past dates come back.
    """
    data = _get(
        "release/dates",
        {
            "release_id": release_id,
            "realtime_start": start,
            "realtime_end": "9999-12-31",
            "include_release_dates_with_no_data": "true",
            "sort_order": "asc",
            "limit": 1000,
        },
    )
    return sorted({d["date"] for d in data.get("release_dates", []) if d["date"] >= start})
