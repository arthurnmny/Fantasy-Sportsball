"""Simple script to fetch leagues from TheSportsDB API.

Rename scripts so they don't shadow standard/third-party module names
(for example, avoid filenames like `requests.py`).
"""

import requests
import json
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse


API_KEY = "123"
# Keep the same URL you were using — update if you want a v1 endpoint
#url = "https://www.thesportsdb.com/api/v1/json"
# We will build event-specific URLs inside lookup_events; no global URL needed


def lookup_events(event_ids, api_key: str = API_KEY):
    """Fetch events by ID from TheSportsDB and print basic info.

    Returns a list of event objects collected from the API.
    """
    collected = []

    for event_id in event_ids:
        api_call_url = f"https://www.thesportsdb.com/api/v1/json/{api_key}/lookupevent.php?id={event_id}"
        try:
            resp = requests.get(api_call_url, timeout=10)
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            print(f"Request failed for id {event_id}: {exc}")
            continue

        try:
            storage = resp.json()
        except ValueError:
            print(f"Failed to decode JSON for id {event_id}")
            continue

        events = storage.get("events") or []
        for event in events:
            date_event = event.get("dateEvent")
            home_team = event.get("strHomeTeam")
            away_team = event.get("strAwayTeam")

            print(f"{date_event}: {home_team} vs {away_team}")
            collected.append(event)

    return collected


def _url_to_filename(url: str) -> str:
    """Create a safe filename from a URL's base (netloc + path).

    Examples:
      https://www.thesportsdb.com/api/v1/json -> www.thesportsdb.com_api_v1_json
    """
    parsed = urlparse(url)
    # combine netloc and path
    name = f"{parsed.netloc}{parsed.path}"
    # replace non-alphanumeric (and not dot/underscore/hyphen) with underscore
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    # collapse multiple underscores
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "data"
    return name


def save_json(data, url: str, data_dir: str = "data") -> Path:
    """Save Python-serializable `data` to data_dir/<sanitized_url>.json and return path."""
    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # append timestamp to avoid clobbering previous runs
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{_url_to_filename(url)}_{ts}.json"
    out_path = out_dir / filename

    # Write JSON with indentation for readability
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return out_path


if __name__ == "__main__":
    # Example event IDs (replace or extend as needed)
    event_ids = [2052711, 2052712, 2052713, 2052714]

    events = lookup_events(event_ids)
    if events:
        # Save combined collected events to a JSON file using lookupevent base URL
        base_url = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}/lookupevent.php"
        saved_path = save_json({"events": events}, base_url)
        print(f"Saved combined JSON to: {saved_path}")
    else:
        print("No events collected; nothing saved")



        