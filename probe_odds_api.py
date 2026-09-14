#!/usr/bin/env python3
"""
Throwaway probe for The Odds API. Run once, read the output, then delete.

Purpose: settle the open questions about sport-key coverage and per-call credit
cost against a real key. Every response returns x-requests-last, which is the
authoritative cost of that call -- that header is the whole point of this script.

Usage:
    set ODDS_API_KEY=your-key        (Windows)
    export ODDS_API_KEY=your-key     (bash)
    python probe_odds_api.py

Or put ODDS_API_KEY=your-key in .env and run it bare.

Costs roughly 3-5 credits total. Nothing here is destructive or writes files.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

BASE = "https://api.the-odds-api.com/v4"

# The 7 leagues the fantasy tracker needs, per scope section 1.
EXPECTED = {
    "americanfootball_nfl": "NFL",
    "basketball_nba": "NBA",
    "baseball_mlb": "MLB",
    "icehockey_nhl": "NHL",
    "americanfootball_ncaaf": "NCAAF",
    "basketball_ncaab": "NCAAB",
    "soccer_usa_mls": "MLS",
}

# Sports worth a live /scores probe -- a pro league and both college leagues,
# so we can see whether college coverage is thinner.
SCORES_PROBE = ["baseball_mlb", "americanfootball_ncaaf", "basketball_ncaab"]


def load_key() -> tuple[str, str]:
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if key:
        return key, "environment"
    env = Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ODDS_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val, ".env"
    sys.exit(
        "No ODDS_API_KEY found.\n"
        "  Set it:  export ODDS_API_KEY=your-key   (or add it to .env)\n"
        "  Get one: https://the-odds-api.com/account/"
    )


def mask(key: str) -> str:
    return f"{key[:4]}...{key[-4:]} ({len(key)} chars)"


def call(path: str, key: str, params: dict | None = None) -> requests.Response:
    p = dict(params or {})
    p["apiKey"] = key
    resp = requests.get(BASE + path, params=p, timeout=25)

    cost = resp.headers.get("x-requests-last", "?")
    used = resp.headers.get("x-requests-used", "?")
    remain = resp.headers.get("x-requests-remaining", "?")
    print(f"    HTTP {resp.status_code} | this call cost: {cost} | used: {used} | remaining: {remain}")

    if resp.status_code == 401:
        # The API returns 401 both for a bad key and for an exhausted balance.
        print(f"    401 body: {resp.text[:200]}")
        print("    -> read the message above: it distinguishes bad key from spent quota.")

    return resp


def main() -> None:
    key, source = load_key()
    print(f"Using ODDS_API_KEY from {source}: {mask(key)}\n")

    # ---- 1. Sport key coverage -------------------------------------------------
    print("[1] GET /sports?all=true  -- which of the 7 league keys exist?")
    resp = call("/sports", key, {"all": "true"})
    if resp.status_code != 200:
        print("    Cannot continue without a working key.")
        return

    available = {s["key"]: s for s in resp.json()}
    print(f"    {len(available)} sports returned.\n")
    print(f"    {'league':7} {'key':24} {'found':6} {'in season':9} title")
    print(f"    {'-' * 7} {'-' * 24} {'-' * 6} {'-' * 9} {'-' * 30}")
    missing = []
    for sport_key, label in EXPECTED.items():
        s = available.get(sport_key)
        if s:
            print(f"    {label:7} {sport_key:24} {'yes':6} {str(s.get('active')):9} {s.get('title', '')}")
        else:
            missing.append(sport_key)
            print(f"    {label:7} {sport_key:24} {'NO':6} {'-':9} <-- key not found")

    if missing:
        print(f"\n    !! {len(missing)} expected key(s) missing: {', '.join(missing)}")
        print("    !! Check /sports output above for the real key names.")

    # ---- 2. /scores cost + college coverage ------------------------------------
    print("\n[2] GET /sports/{sport}/scores?daysFrom=3  -- cost and coverage")
    for sport_key in SCORES_PROBE:
        label = EXPECTED.get(sport_key, sport_key)
        print(f"\n  {label} ({sport_key})")
        resp = call(f"/sports/{sport_key}/scores/", key, {"daysFrom": 3})
        if resp.status_code != 200:
            continue
        events = resp.json()
        completed = [e for e in events if e.get("completed")]
        with_scores = [e for e in completed if e.get("scores")]
        print(f"    {len(events)} events returned, {len(completed)} completed, {len(with_scores)} with scores")
        for e in with_scores[:2]:
            sc = ", ".join(f"{s['name']} {s['score']}" for s in e["scores"])
            print(f"      {e['commence_time'][:10]}  {sc}")

    # ---- 3. What remains --------------------------------------------------------
    print("\n[DONE] Note the 'remaining' figure above -- that's your real tier size.")
    print("       Delete this script once you've read the output.")


if __name__ == "__main__":
    main()
