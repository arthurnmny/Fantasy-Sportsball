from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from pathlib import Path
import csv
import requests
import json
import time
from datetime import datetime

API_KEY = "3"
DATA_CSV = Path("data/custom_league_teams.csv")
OUT_JSON = Path("data/latest_wins.json")

app = FastAPI()
scheduler = BackgroundScheduler()


class RunResponse(BaseModel):
    status: str
    run_at: datetime


def read_custom_teams():
    if not DATA_CSV.exists():
        return []
    rows = []
    with DATA_CSV.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            league = (r.get("league") or "").strip()
            team = (r.get("team") or "").strip()
            if league and team:
                rows.append((league, team))
    return rows


def fetch_team_search(team_name):
    # searchteams.php?t=Team+Name
    url = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}/searchteams.php?t={requests.utils.requote_uri(team_name)}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_last_events_for_team(team_id):
    # eventslast.php?id=TEAM_ID
    url = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}/eventslast.php?id={team_id}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def determine_win_for_team_events(team_name, events):
    # events is expected to be a list of event dicts; examine the most recent
    if not events:
        return None
    event = events[0]
    # typical fields: strHomeTeam, strAwayTeam, intHomeScore, intAwayScore
    home = event.get("strHomeTeam")
    away = event.get("strAwayTeam")
    try:
        home_score = int(event.get("intHomeScore") or -1)
        away_score = int(event.get("intAwayScore") or -1)
    except ValueError:
        return None

    if home_score < 0 or away_score < 0:
        return None

    if team_name == home:
        return home_score > away_score
    elif team_name == away:
        return away_score > home_score
    else:
        return None


def run_job():
    results = []
    entries = read_custom_teams()
    for league, team in entries:
        # find the team to get the team id
        try:
            search = fetch_team_search(team)
        except Exception as exc:
            results.append({"league": league, "team": team, "error": str(exc)})
            continue

        teams = search.get("teams") or []
        if not teams:
            results.append({"league": league, "team": team, "error": "team not found"})
            continue

        # choose first matching team
        team_obj = teams[0]
        team_id = team_obj.get("idTeam")

        # fetch last events and determine if the last event was a win
        try:
            events_resp = fetch_last_events_for_team(team_id)
            events = events_resp.get("results") or events_resp.get("event") or events_resp.get("events") or []
        except Exception as exc:
            results.append({"league": league, "team": team, "team_id": team_id, "error": str(exc)})
            continue

        win = determine_win_for_team_events(team, events)
        results.append({
            "league": league,
            "team": team,
            "team_id": team_id,
            "last_checked": datetime.utcnow().isoformat(),
            "last_win": win,
        })

        # small pause to be polite
        time.sleep(0.5)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({"run_at": datetime.utcnow().isoformat(), "results": results}, indent=2), encoding="utf-8")
    return results


@app.on_event("startup")
def startup():
    # schedule weekly run
    scheduler.add_job(run_job, "cron", day_of_week="mon", hour=6, minute=0)
    scheduler.start()


@app.get("/results")
def get_results():
    if not OUT_JSON.exists():
        return {"status": "no runs yet"}
    return json.loads(OUT_JSON.read_text(encoding="utf-8"))


@app.post("/run-now", response_model=RunResponse)
def run_now(background_tasks: BackgroundTasks):
    # Run in background and return immediate response
    background_tasks.add_task(run_job)
    return {"status": "started", "run_at": datetime.utcnow()}
