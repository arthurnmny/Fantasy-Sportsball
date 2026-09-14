"""Fetch all team names for each league in data/league_names.txt and save to CSV.

Output: data/league_teams.csv with columns: league,team
"""

import argparse
import csv
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests

API_KEY = "3"
LEAGUE_NAMES_FILE = Path("data/league_names.txt")
OUT_CSV = Path("data/league_teams.csv")


def read_league_names(path: Path):
    if not path.exists():
        print(f"League names file not found: {path}")
        return []

    with path.open("r", encoding="utf-8") as f:
        names = [line.strip() for line in f if line.strip()]
    return names


def fetch_teams_for_league(league_name: str, api_key: str = API_KEY):
    """Return list of team names for the given league_name."""
    encoded = quote_plus(league_name)
    url = f"https://www.thesportsdb.com/api/v1/json/{api_key}/search_all_teams.php?l={encoded}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        # let caller decide how to handle retries/backoff
        raise

    try:
        data = resp.json()
    except ValueError:
        print(f"Invalid JSON for league '{league_name}'")
        return []

    teams = data.get("teams") or []
    names = []
    for t in teams:
        name = t.get("strTeam")
        if name:
            names.append(name)
    return names


def main():
    parser = argparse.ArgumentParser(description="Fetch teams for leagues and save to CSV")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between requests (default 1.0)")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries per request on failure")
    parser.add_argument("--backoff-factor", type=float, default=1.0, help="Backoff factor for retries (seconds)")
    parser.add_argument("--resume", action="store_true", help="If set, skip leagues already present in the CSV")
    args = parser.parse_args()

    leagues = read_league_names(LEAGUE_NAMES_FILE)
    if not leagues:
        print("No leagues to process")
        return

    # If resume enabled and CSV exists, read already processed leagues to skip them
    processed_leagues = set()
    if args.resume and OUT_CSV.exists():
        try:
            with OUT_CSV.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    processed_leagues.add(row.get("league"))
        except Exception:
            # if reading fails, continue without resume
            processed_leagues = set()

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    # Open CSV in append mode so we can save progress as we go
    write_header = not OUT_CSV.exists()
    total_written = 0
    with OUT_CSV.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["league", "team"])

        for idx, league in enumerate(leagues, 1):
            if args.resume and league in processed_leagues:
                print(f"[{idx}/{len(leagues)}] Skipping already-processed league: {league}")
                continue

            print(f"[{idx}/{len(leagues)}] Fetching teams for league: {league}")

            # retry loop with exponential backoff
            attempt = 0
            while attempt <= args.max_retries:
                attempt += 1
                try:
                    teams = fetch_teams_for_league(league)
                    break
                except requests.RequestException as exc:
                    if attempt > args.max_retries:
                        print(f"Failed after {args.max_retries} retries for league '{league}': {exc}")
                        teams = []
                        break
                    sleep_for = args.backoff_factor * (2 ** (attempt - 1))
                    print(f"Request failed (attempt {attempt}) for '{league}': {exc}. Backing off {sleep_for:.1f}s")
                    time.sleep(sleep_for)

            if teams:
                for team in teams:
                    writer.writerow((league, team))
                total_written += len(teams)

            # be gentle to the API between league requests
            time.sleep(args.delay)

    print(f"Saved {total_written} newly fetched teams to {OUT_CSV}")


if __name__ == "__main__":
    main()
