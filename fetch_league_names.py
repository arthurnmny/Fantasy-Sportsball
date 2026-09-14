"""Fetch all league names from TheSportsDB and save them to a text file.

Usage: run the script; it will write data/league_names.txt (one league name per line).
"""

import requests
from pathlib import Path

API_KEY = "3"


def fetch_league_names(api_key: str = API_KEY):
    """Return a list of league names from the all_leagues endpoint."""
    url = f"https://www.thesportsdb.com/api/v1/json/{api_key}/all_leagues.php"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        print(f"Request failed: {exc}")
        return []

    try:
        data = resp.json()
    except ValueError:
        print("Failed to decode JSON response")
        return []

    leagues = data.get("leagues") or []
    names = []
    for item in leagues:
        # TheSportsDB typically returns strLeague
        name = item.get("strLeague") or item.get("name")
        if name:
            names.append(name)

    return names


def save_names_txt(names, out_path: str = "data/league_names.txt") -> Path:
    """Save the list of names to a UTF-8 text file, one name per line."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for n in names:
            f.write(n + "\n")
    return p


if __name__ == "__main__":
    names = fetch_league_names()
    if not names:
        print("No league names fetched")
    else:
        out = save_names_txt(names)
        print(f"Saved {len(names)} league names to {out}")
