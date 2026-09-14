"""
Seed the roster: the top 8 teams of every league, randomly assigned across 8
placeholder owners.

There is no 2026 draft to replay (the season is already in flight), so the
roster is synthesised instead: rank each league's teams by its configured
source, take the top 8, then deal them out to the 8 members with a fixed RNG
seed so the same command always produces the same league.

Assignment is per-league and independent, which is what guarantees the two
roster invariants: every member owns exactly one team in every league, and no
team is owned twice. Both are enforced by unique constraints on OwnedTeam, so a
bug here fails loudly at insert rather than producing a quietly illegal roster.

Usage:
    python seed_roster.py                 # seed an empty database
    python seed_roster.py --force         # wipe and re-seed
    python seed_roster.py --show-current  # print the existing roster, change nothing
"""
from __future__ import annotations

import argparse
import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import db as db_module
from espn_client import (
    ClientConfig,
    TeamRef,
    fetch_rankings,
    fetch_standings,
    stat_value,
    team_ref_from_raw,
)
from leagues import LEAGUES, LeagueConfig
from models import League, Member, OwnedTeam

MEMBERS_COUNT = 8
TEAMS_PER_LEAGUE = 8
DEFAULT_RNG_SEED = 42
MEMBER_NAMES = [f"Owner {i}" for i in range(1, MEMBERS_COUNT + 1)]


def _as_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def top_teams(league: LeagueConfig, client_cfg: ClientConfig) -> list[TeamRef]:
    """
    The top TEAMS_PER_LEAGUE teams for one league, best first.

    Standings come back unsorted and conference-grouped, so they are flattened
    (in espn_client) and sorted here by the league's configured stat. Poll-based
    leagues are already in rank order.
    """
    if league.ranking_source == "poll":
        return fetch_rankings(league.espn_path, client_cfg)[:TEAMS_PER_LEAGUE]

    if league.seed_season is None or league.sort_stat is None:
        raise SystemExit(f"League {league.key} has no standings-based seed config.")

    entries = fetch_standings(league.espn_path, league.seed_season, client_cfg)
    scored: list[tuple[float, TeamRef]] = []
    seen: set[str] = set()
    for entry in entries:
        ref = team_ref_from_raw(entry.get("team") or {})
        score = _as_float(stat_value(entry, league.sort_stat))
        if not ref.espn_team_id or score is None or ref.espn_team_id in seen:
            continue
        seen.add(ref.espn_team_id)
        scored.append((score, ref))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [ref for _, ref in scored[:TEAMS_PER_LEAGUE]]


def check_roster_shape(league: LeagueConfig, refs: list[TeamRef]) -> list[str]:
    """
    Structural check on one league's resolved teams.

    Deliberately NOT a check against ESPN's /teams endpoint. That endpoint
    returns only 50 teams for the college leagues (which have 134 and 360+
    respectively), so it cannot confirm a college roster -- two of eight NCAAB
    teams passed such a check purely by falling inside the truncation. A real
    existence check happens in extract_results.py instead, where each team id is
    actually resolved against the schedule endpoint.
    """
    problems: list[str] = []
    if len(refs) != TEAMS_PER_LEAGUE:
        problems.append(
            f"{league.key}: resolved {len(refs)} teams, need {TEAMS_PER_LEAGUE}"
        )
    missing_id = [ref.display_name or "?" for ref in refs if not ref.espn_team_id]
    if missing_id:
        problems.append(f"{league.key}: teams with no ESPN id: {', '.join(missing_id)}")
    unnamed = [ref.espn_team_id for ref in refs if not ref.display_name]
    if unnamed:
        problems.append(f"{league.key}: teams with no name: {', '.join(unnamed)}")
    ids = [ref.espn_team_id for ref in refs]
    if len(set(ids)) != len(ids):
        problems.append(f"{league.key}: duplicate team ids in the top {TEAMS_PER_LEAGUE}")
    return problems


def assign_to_members(
    league_teams: dict[str, list[TeamRef]], rng: random.Random
) -> dict[str, list[tuple[str, TeamRef]]]:
    """
    Deal each league's teams to the members.

    One shuffle per league, dealt in member order -- so a member's seven teams
    are independent draws, not a single permuted block.
    """
    assignments: dict[str, list[tuple[str, TeamRef]]] = {name: [] for name in MEMBER_NAMES}
    for league_key, refs in league_teams.items():
        shuffled = list(refs)
        rng.shuffle(shuffled)
        for member_name, ref in zip(MEMBER_NAMES, shuffled):
            assignments[member_name].append((league_key, ref))
    return assignments


def show_current(session: Session) -> None:
    rows = session.execute(
        select(Member.name, League.name, OwnedTeam.team_name)
        .join(OwnedTeam, OwnedTeam.member_id == Member.id)
        .join(League, OwnedTeam.league_id == League.id)
        .order_by(Member.name, League.name)
    ).all()
    if not rows:
        print("No roster seeded yet.")
        return
    print(f"Roster: {len(rows)} owned teams")
    current_member = None
    for member_name, league_name, team_name in rows:
        if member_name != current_member:
            current_member = member_name
            print(f"\n  {member_name}")
        print(f"    {league_name:<7} {team_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    parser.add_argument("--seed", type=int, default=DEFAULT_RNG_SEED, help="RNG seed for the deal")
    parser.add_argument("--force", action="store_true", help="Drop and rebuild every table, then re-seed")
    parser.add_argument("--show-current", action="store_true", help="Print the existing roster and exit")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between requests")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--backoff-factor", type=float, default=1.0)
    args = parser.parse_args()

    engine = db_module.make_engine(args.db)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)

    if args.show_current:
        with session_factory() as session:
            show_current(session)
        return

    with session_factory() as session:
        existing = session.execute(select(func.count()).select_from(OwnedTeam)).scalar_one()
        if existing and not args.force:
            raise SystemExit(
                f"Roster already has {existing} owned teams. "
                "Use --show-current to inspect it, or --force to wipe and re-seed."
            )
        if args.force:
            print("--force: dropping and recreating every table.\n")
            db_module.reset_db(engine)

    client_cfg = ClientConfig(
        delay=args.delay, max_retries=args.max_retries, backoff_factor=args.backoff_factor
    )

    print(f"Ranking the top {TEAMS_PER_LEAGUE} of each league...\n")
    league_teams: dict[str, list[TeamRef]] = {}
    problems: list[str] = []
    for league in LEAGUES:
        source = "AP poll" if league.ranking_source == "poll" else (
            f"standings ({league.sort_stat}, season {league.seed_season})"
        )
        refs = top_teams(league, client_cfg)
        league_teams[league.key] = refs
        print(f"  {league.key:<7} {len(refs):>2} teams from {source}")
        problems.extend(check_roster_shape(league, refs))

    if problems:
        print("\nRefusing to seed an incomplete roster:")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)

    rng = random.Random(args.seed)
    assignments = assign_to_members(league_teams, rng)
    for member_name in MEMBER_NAMES:
        if len(assignments[member_name]) != len(LEAGUES):
            raise SystemExit(f"{member_name} ended up with {len(assignments[member_name])} teams")

    with session_factory() as session:
        league_rows: dict[str, League] = {}
        for league in LEAGUES:
            league_rows[league.key] = League(
                name=league.key,
                espn_path=league.espn_path,
                ranking_source=league.ranking_source,
            )
            session.add(league_rows[league.key])

        for member_name in MEMBER_NAMES:
            member = Member(name=member_name)
            session.add(member)
            session.flush()  # need member.id before the OwnedTeam rows
            for league_key, ref in assignments[member_name]:
                session.add(
                    OwnedTeam(
                        member_id=member.id,
                        league_id=league_rows[league_key].id,
                        team_name=ref.display_name,
                        espn_team_id=ref.espn_team_id,
                    )
                )
        session.commit()

    total = sum(len(v) for v in assignments.values())
    print(f"\nSeeded {len(MEMBER_NAMES)} members, {len(LEAGUES)} leagues, {total} owned teams.")
    print(f"(deal reproducible with --seed {args.seed})\n")

    with session_factory() as session:
        show_current(session)


if __name__ == "__main__":
    main()
