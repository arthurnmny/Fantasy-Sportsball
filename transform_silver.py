"""
Bronze -> Silver transformations.

Each function is idempotent: it deletes and rebuilds the silver rows derived
from a given bronze source, so re-running after new bronze data arrives is
always safe (no duplicate rows, no manual cleanup).

Stages
------
The silver tables do not all depend on the same bronze inputs, and one of them
depends on a table that does not exist until the aggregation job has run:

    GameResult        --(games)-->    SilverGameFact
    SilverGameFact    --(aggregate)-->  Matchup
    Matchup           --(derived)-->  SilverMatchupFact
    Schedule          --(derived)-->  SilverScheduleResolved

So the pipeline runs this script twice -- once for `games`, then again for
`derived` after aggregate_matchups.py. `--stage all` does both, which is
correct only when matchups are already up to date.

Usage:
    python transform_silver.py --stage games
    python transform_silver.py --stage derived
    python transform_silver.py              # both
"""
from __future__ import annotations

import argparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import db as db_module
from models import (
    GameResult,
    League,
    Matchup,
    Member,
    OwnedTeam,
    Schedule,
    local_period,
    points_for_scores,
)
from silver_models import SilverGameFact, SilverMatchupFact, SilverScheduleResolved


def build_silver_game_facts(session: Session) -> int:
    """
    Rebuild silver_game_facts from every GameResult, flattened against its
    OwnedTeam, Member and League.

    Outcome and points are computed here from the two scores -- the only place
    the scoring rule is applied. Bronze deliberately stores neither.
    """
    session.execute(delete(SilverGameFact))

    results = session.execute(
        select(GameResult, OwnedTeam, Member, League)
        .join(OwnedTeam, GameResult.owned_team_id == OwnedTeam.id)
        .join(Member, OwnedTeam.member_id == Member.id)
        .join(League, OwnedTeam.league_id == League.id)
    ).all()

    rows_built = 0
    for result, owned_team, member, league in results:
        outcome, points = points_for_scores(result.team_score, result.opponent_score)
        session.add(
            SilverGameFact(
                source_result_id=result.id,
                owned_team_id=owned_team.id,
                member_id=member.id,
                member_name=member.name,
                league_id=league.id,
                league_name=league.name,
                team_name=owned_team.team_name,
                opponent_name=result.opponent_name,
                commence_time=result.commence_time,
                period=local_period(result.commence_time),
                is_home=result.is_home,
                team_score=result.team_score,
                opponent_score=result.opponent_score,
                outcome=outcome,
                points=points,
            )
        )
        rows_built += 1

    session.commit()
    return rows_built


def build_silver_matchup_facts(session: Session) -> int:
    """
    Rebuild silver_matchup_facts from every finalized Matchup.

    Only `is_final` matchups qualify: a period still in flight has running
    totals that must never reach the standings.
    """
    session.execute(delete(SilverMatchupFact))

    matchups = session.execute(
        select(Matchup, Schedule)
        .join(Schedule, Matchup.schedule_id == Schedule.id)
        .where(Matchup.is_final.is_(True))
    ).all()

    member_names: dict[int, str] = {
        m.id: m.name for m in session.execute(select(Member)).scalars().all()
    }

    rows_built = 0
    for matchup, schedule in matchups:
        if schedule.member_a_id is None or schedule.member_b_id is None:
            continue  # bye round or an unresolvable pairing -- nothing to record

        winner_name = member_names.get(matchup.winner_id) if matchup.winner_id else None
        session.add(
            SilverMatchupFact(
                source_matchup_id=matchup.id,
                schedule_id=schedule.id,
                period=schedule.period,
                round_number=schedule.round_number,
                is_playoff=schedule.is_playoff,
                round_name=schedule.round_name,
                member_a_id=schedule.member_a_id,
                member_a_name=member_names.get(schedule.member_a_id, "Unknown"),
                member_a_points=matchup.member_a_points,
                member_b_id=schedule.member_b_id,
                member_b_name=member_names.get(schedule.member_b_id, "Unknown"),
                member_b_points=matchup.member_b_points,
                winner_id=matchup.winner_id,
                winner_name=winner_name,
                margin=abs(matchup.member_a_points - matchup.member_b_points),
            )
        )
        rows_built += 1

    session.commit()
    return rows_built


def build_silver_schedule_resolved(session: Session) -> int:
    """Rebuild silver_schedule_resolved from Schedule rows that have both members set."""
    session.execute(delete(SilverScheduleResolved))

    resolved = session.execute(
        select(Schedule)
        .where(Schedule.member_a_id.is_not(None), Schedule.member_b_id.is_not(None))
    ).scalars().all()

    rows_built = 0
    for row in resolved:
        session.add(
            SilverScheduleResolved(
                source_schedule_id=row.id,
                period=row.period,
                round_number=row.round_number,
                member_a_id=row.member_a_id,
                member_b_id=row.member_b_id,
                is_playoff=row.is_playoff,
                round_name=row.round_name,
            )
        )
        rows_built += 1

    session.commit()
    return rows_built


def build_games_stage(session: Session) -> dict[str, int]:
    return {"silver_game_facts": build_silver_game_facts(session)}


def build_derived_stage(session: Session) -> dict[str, int]:
    return {
        "silver_matchup_facts": build_silver_matchup_facts(session),
        "silver_schedule_resolved": build_silver_schedule_resolved(session),
    }


def build_all_silver(session: Session) -> dict[str, int]:
    """Both stages in dependency order and return row counts."""
    counts = build_games_stage(session)
    counts.update(build_derived_stage(session))
    return counts


STAGES = {
    "games": build_games_stage,
    "derived": build_derived_stage,
    "all": build_all_silver,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    parser.add_argument(
        "--stage",
        choices=sorted(STAGES),
        default="all",
        help="Which silver tables to rebuild (default all)",
    )
    args = parser.parse_args()

    engine = db_module.make_engine(args.db)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)

    with session_factory() as session:
        counts = STAGES[args.stage](session)

    print(f"Silver rebuilt (stage={args.stage}):")
    for table, count in counts.items():
        print(f"  {table:<28} {count:>6} rows")


if __name__ == "__main__":
    main()
