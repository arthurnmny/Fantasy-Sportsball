"""
ESPN public API client: HTTP, retries, and normalization.

ESPN's endpoints are free, keyless, and undocumented. Several of them are
inconsistent with each other in ways that matter, so all responses funnel
through the normalizers here rather than being read raw at the call site:

- `score` is a *string* on /scoreboard but an *object* ({value, displayValue})
  on /teams/{id}/schedule. normalize_score() accepts either.
- Standings are grouped under `children[]` (conferences) and are NOT pre-sorted;
  the playoffSeed stat is conference-relative, so it cannot rank league-wide.
  fetch_standings() flattens; the caller sorts.
- College football rankings expose the school name in `nickname`, not
  `displayName`, which is absent. team_ref_from_raw() walks the fallbacks.

Datetimes are returned as **naive UTC** throughout, matching the convention
used for the datetime columns in models.py.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

SITE_BASE = "https://site.api.espn.com/apis/site/v2/sports"
# Standings live under a different base than teams/schedules/rankings.
CORE_BASE = "https://site.api.espn.com/apis/v2/sports"


@dataclass
class ClientConfig:
    delay: float = 0.5
    max_retries: int = 3
    backoff_factor: float = 1.0
    timeout: int = 20


@dataclass(frozen=True)
class TeamRef:
    """A team as ESPN identifies it: opaque id plus a display name."""

    espn_team_id: str
    display_name: str
    abbreviation: str = ""


@dataclass(frozen=True)
class GameRecord:
    """One completed game, from the perspective of one owned team."""

    espn_event_id: str
    commence_time: datetime
    opponent_name: str
    opponent_espn_team_id: str | None
    team_score: int
    opponent_score: int
    is_home: bool


_session = requests.Session()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _request_json(url: str, params: dict | None, cfg: ClientConfig):
    """
    GET a URL and return parsed JSON, retrying with exponential backoff.

    Raises requests.RequestException if every attempt fails. Returns None if
    the response body is not JSON (mirroring fetch_teams_by_league.py, which
    treats a decode failure as an empty result rather than a retryable error).
    """
    last_exc: Exception | None = None
    for attempt in range(1, cfg.max_retries + 2):
        try:
            resp = _session.get(url, params=params or {}, timeout=cfg.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt > cfg.max_retries:
                raise
            sleep_for = cfg.backoff_factor * (2 ** (attempt - 1))
            print(f"    request failed (attempt {attempt}): {exc}. Backing off {sleep_for:.1f}s")
            time.sleep(sleep_for)
            continue
        finally:
            # Be gentle between requests whether or not this one succeeded.
            time.sleep(cfg.delay)

        try:
            return resp.json()
        except ValueError:
            print(f"    invalid JSON from {url}")
            return None

    if last_exc is not None:  # pragma: no cover - loop either returns or raises
        raise last_exc
    return None


# --------------------------------------------------------------------------
# Normalizers
# --------------------------------------------------------------------------


def normalize_score(raw) -> int | None:
    """
    Coerce an ESPN score into an int, or None if it is absent/not a number.

    Handles the three shapes ESPN actually returns: a bare number, a numeric
    string ("9"), and the {value, displayValue} object used by team schedules.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, dict):
        if raw.get("value") is not None:
            return normalize_score(raw["value"])
        return normalize_score(raw.get("displayValue"))
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def parse_commence_time(raw) -> datetime | None:
    """Parse an ESPN ISO timestamp into a naive UTC datetime."""
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def team_ref_from_raw(team: dict) -> TeamRef:
    """
    Build a TeamRef from an ESPN team object.

    The name fallback chain matters: college football rankings carry the school
    in `nickname` with `displayName` absent, while standings and /teams carry
    `displayName`. Without the fallback those teams come back nameless.
    """
    if not team:
        return TeamRef("", "")
    espn_id = str(team.get("id") or "").strip()
    for field in ("displayName", "nickname", "location", "name", "shortDisplayName"):
        value = (team.get(field) or "").strip()
        if value:
            return TeamRef(espn_id, value, (team.get("abbreviation") or "").strip())
    return TeamRef(espn_id, "", (team.get("abbreviation") or "").strip())


def stat_value(entry: dict, name: str):
    """Pull one named stat out of a standings entry's stats array."""
    for stat in entry.get("stats") or []:
        if stat.get("name") == name:
            return stat.get("value")
    return None


def season_params_for_window(
    window_start: datetime, window_end: datetime, season_year_mode: str
) -> list[int]:
    """
    Which ESPN `season` labels can contain games inside [window_start, window_end].

    Deliberately generous by one season at the margin: the date filter in the
    extractor removes anything outside the window, so an extra request costs
    one HTTP call while a missing season silently loses real games.
    """
    if season_year_mode == "ending":
        # A season labelled Y spans autumn Y-1 to spring Y, so a window inside
        # year Y can touch both season Y (its spring half) and season Y+1
        # (its autumn half).
        return list(range(window_start.year, window_end.year + 2))
    # "starting": a season labelled Y is played within calendar year Y. The
    # -1 covers a January window picking up the previous season's tail.
    return list(range(window_start.year - 1, window_end.year + 1))


# --------------------------------------------------------------------------
# Fetchers
# --------------------------------------------------------------------------


def fetch_team_schedule(
    espn_path: str, team_id: str, season: int, cfg: ClientConfig | None = None
) -> list[dict]:
    """
    One team's season schedule. Returns the raw `events` array.

    Note this covers the regular season only -- ESPN omits playoffs from this
    endpoint's default response.
    """
    cfg = cfg or ClientConfig()
    data = _request_json(
        f"{SITE_BASE}/{espn_path}/teams/{team_id}/schedule", {"season": season}, cfg
    )
    if not data:
        return []
    return data.get("events") or []


def fetch_standings(
    espn_path: str, season: int, cfg: ClientConfig | None = None
) -> list[dict]:
    """
    Flattened standings entries across all conferences/divisions.

    ESPN nests these under children[] and returns them in no useful order, so
    the caller is responsible for sorting.
    """
    cfg = cfg or ClientConfig()
    data = _request_json(f"{CORE_BASE}/{espn_path}/standings", {"season": season}, cfg)
    if not data:
        return []

    entries: list[dict] = []
    for child in data.get("children") or []:
        entries.extend((child.get("standings") or {}).get("entries") or [])
    if not entries:
        # Some leagues put entries at the top level with no children wrapper.
        entries = (data.get("standings") or {}).get("entries") or []
    return entries


def fetch_rankings(
    espn_path: str, cfg: ClientConfig | None = None, poll_type: str = "ap"
) -> list[TeamRef]:
    """
    A poll's ranked teams, best first.

    Used for college football, whose standings publish no cross-conference
    ranking metric (no winPercent, no losses) and so cannot produce a top 8.
    """
    cfg = cfg or ClientConfig()
    data = _request_json(f"{SITE_BASE}/{espn_path}/rankings", None, cfg)
    if not data:
        return []

    polls = data.get("rankings") or []
    poll = next((p for p in polls if p.get("type") == poll_type), None)
    if poll is None:
        poll = polls[0] if polls else None
    if poll is None:
        return []

    ranks = sorted(poll.get("ranks") or [], key=lambda r: r.get("current") or 9999)
    refs = [team_ref_from_raw(rank.get("team") or {}) for rank in ranks]
    return [ref for ref in refs if ref.espn_team_id]


def games_for_team(
    espn_path: str,
    team_id: str,
    seasons: list[int],
    cfg: ClientConfig | None = None,
) -> list[GameRecord]:
    """
    Every completed game for one team across the given season labels.

    Deduplicated by event id, since a game near a season boundary can appear in
    two season responses. Games that ESPN marks completed but that carry no
    score (cancellations, no-contests) are dropped.
    """
    cfg = cfg or ClientConfig()
    by_event: dict[str, GameRecord] = {}
    for season in seasons:
        events = fetch_team_schedule(espn_path, team_id, season, cfg)
        for event in events:
            record = _game_record_from_event(event, team_id)
            if record is not None and record.espn_event_id:
                by_event[record.espn_event_id] = record
    return list(by_event.values())


def _find_competitor(competitors: list[dict], team_id: str) -> dict | None:
    target = str(team_id)
    for competitor in competitors:
        if str((competitor.get("team") or {}).get("id") or "") == target:
            return competitor
    for competitor in competitors:
        if str(competitor.get("id") or "") == target:
            return competitor
    return None


def _game_record_from_event(event: dict, team_id: str) -> GameRecord | None:
    """Turn one schedule event into a GameRecord for `team_id`, or None to skip it."""
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]

    status = (competition.get("status") or {}).get("type") or {}
    if not status.get("completed"):
        return None

    competitors = competition.get("competitors") or []
    mine = _find_competitor(competitors, team_id)
    if mine is None:
        return None
    theirs = next((c for c in competitors if c is not mine), None)
    if theirs is None:
        return None

    team_score = normalize_score(mine.get("score"))
    opponent_score = normalize_score(theirs.get("score"))
    if team_score is None or opponent_score is None:
        return None

    commence = parse_commence_time(event.get("date") or competition.get("date"))
    if commence is None:
        return None

    opponent_ref = team_ref_from_raw(theirs.get("team") or {})
    return GameRecord(
        espn_event_id=str(event.get("id") or competition.get("id") or ""),
        commence_time=commence,
        opponent_name=opponent_ref.display_name or "Unknown",
        opponent_espn_team_id=(
            opponent_ref.espn_team_id or str(theirs.get("id") or "") or None
        ),
        team_score=team_score,
        opponent_score=opponent_score,
        is_home=(mine.get("homeAway") == "home"),
    )
