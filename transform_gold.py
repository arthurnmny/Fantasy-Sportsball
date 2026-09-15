"""
Silver -> Gold transformations.

Gold tables are fully rebuilt on each run (delete + reinsert), not incrementally
updated -- simplest correct approach at this data volume (8 members, 56 teams,
one season). Revisit if the season history grows large enough that a full
rebuild gets slow.

Note on `season_points` vs the W-L-T record: points are summed across every
game played, including the period currently in flight, while the record only
counts finalized matchups. That asymmetry is intentional -- the record is
head-to-head standing, the point total is the seeding tiebreaker and should
reflect the season as it stands right now.

Usage:
    python transform_gold.py
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import db as db_module
from gold_models import (
    GoldLeagueBreakdown,
    GoldMemberPeriodScore,
    GoldPlayoffBracket,
    GoldStandings,
    GoldTeamLeaderboard,
)
from models import League, Member, OwnedTeam
from silver_models import SilverGameFact, SilverMatchupFact


def total_points(values) -> float:
    """
    Sum weighted points and round to 2dp.

    Every silver point value has at most two decimals, so the true sum does too.
    Rounding here strips float accumulation noise, which keeps the gold-vs-silver
    reconciliation an exact equality check rather than a tolerance check.
    """
    return round(sum(values), 2)


def build_gold_standings(session: Session) -> int:
    """
    One row per member: head-to-head record from finalized matchups, plus
    cumulative season points (the seeding tiebreaker).
    """
    session.execute(delete(GoldStandings))

    members = session.execute(select(Member)).scalars().all()
    facts = session.execute(select(SilverMatchupFact)).scalars().all()
    game_facts = session.execute(select(SilverGameFact)).scalars().all()

    record: dict[int, dict[str, int]] = {m.id: {"wins": 0, "losses": 0, "ties": 0} for m in members}
    for fact in facts:
        if fact.member_a_points > fact.member_b_points:
            record[fact.member_a_id]["wins"] += 1
            record[fact.member_b_id]["losses"] += 1
        elif fact.member_b_points > fact.member_a_points:
            record[fact.member_b_id]["wins"] += 1
            record[fact.member_a_id]["losses"] += 1
        else:
            record[fact.member_a_id]["ties"] += 1
            record[fact.member_b_id]["ties"] += 1

    by_member: dict[int, list[float]] = defaultdict(list)
    for fact in game_facts:
        by_member[fact.member_id].append(fact.points)
    # .get with a 0 default rather than direct indexing: a member whose teams
    # have not played yet has no entry at all.
    season_points: dict[int, float] = {
        member_id: total_points(points) for member_id, points in by_member.items()
    }

    # Seed by record first (wins desc, losses asc), then season points.
    ranked = sorted(
        members,
        key=lambda m: (
            -record[m.id]["wins"],
            record[m.id]["losses"],
            -season_points.get(m.id, 0.0),
        ),
    )

    for seed, member in enumerate(ranked, start=1):
        session.add(
            GoldStandings(
                member_id=member.id,
                member_name=member.name,
                wins=record[member.id]["wins"],
                losses=record[member.id]["losses"],
                ties=record[member.id]["ties"],
                season_points=season_points.get(member.id, 0.0),
                current_seed=seed,
            )
        )

    session.commit()
    return len(ranked)


def build_gold_member_period_scores(session: Session) -> int:
    """One row per member per period -- feeds the score-over-time trend chart."""
    session.execute(delete(GoldMemberPeriodScore))

    game_facts = session.execute(select(SilverGameFact)).scalars().all()
    matchup_facts = session.execute(select(SilverMatchupFact)).scalars().all()

    by_member_period: dict[tuple[int, str], list[float]] = defaultdict(list)
    for fact in game_facts:
        by_member_period[(fact.member_id, fact.period)].append(fact.points)
    points_by_member_period = {
        key: total_points(points) for key, points in by_member_period.items()
    }

    result_lookup: dict[tuple[int, str], tuple[str, int]] = {}
    for fact in matchup_facts:
        if fact.member_a_points > fact.member_b_points:
            a_result, b_result = "win", "loss"
        elif fact.member_b_points > fact.member_a_points:
            a_result, b_result = "loss", "win"
        else:
            a_result, b_result = "tie", "tie"
        result_lookup[(fact.member_a_id, fact.period)] = (a_result, fact.member_b_id)
        result_lookup[(fact.member_b_id, fact.period)] = (b_result, fact.member_a_id)

    rows_built = 0
    for (member_id, period), points in points_by_member_period.items():
        matchup_result, opponent_id = result_lookup.get((member_id, period), (None, None))
        session.add(
            GoldMemberPeriodScore(
                member_id=member_id,
                period=period,
                points_scored=points,
                opponent_id=opponent_id,
                matchup_result=matchup_result,
            )
        )
        rows_built += 1

    session.commit()
    return rows_built


def build_gold_team_leaderboard(session: Session) -> int:
    """
    One row per owned team for the season -- answers 'which team is carrying me.'

    Names come from the OwnedTeam join rather than from a game fact, so a team
    that has not played yet still gets a correctly labelled zero row.
    """
    session.execute(delete(GoldTeamLeaderboard))

    owned_teams = session.execute(
        select(OwnedTeam, Member, League)
        .join(Member, OwnedTeam.member_id == Member.id)
        .join(League, OwnedTeam.league_id == League.id)
    ).all()
    game_facts = session.execute(select(SilverGameFact)).scalars().all()

    by_team: dict[int, list[SilverGameFact]] = defaultdict(list)
    for fact in game_facts:
        by_team[fact.owned_team_id].append(fact)

    rows_built = 0
    for team, member, league in owned_teams:
        team_games = by_team.get(team.id, [])
        session.add(
            GoldTeamLeaderboard(
                owned_team_id=team.id,
                member_id=member.id,
                member_name=member.name,
                league_id=league.id,
                league_name=league.name,
                team_name=team.team_name,
                games_played=len(team_games),
                wins=sum(1 for g in team_games if g.outcome.value == "win"),
                losses=sum(1 for g in team_games if g.outcome.value == "loss"),
                ties=sum(1 for g in team_games if g.outcome.value == "tie"),
                total_points=total_points(g.points for g in team_games),
            )
        )
        rows_built += 1

    session.commit()
    return rows_built


def build_gold_league_breakdown(session: Session) -> int:
    """One row per (member, league) -- which league is carrying each member's score."""
    session.execute(delete(GoldLeagueBreakdown))

    game_facts = session.execute(select(SilverGameFact)).scalars().all()

    grouped: dict[tuple[int, int], dict] = {}
    for fact in game_facts:
        key = (fact.member_id, fact.league_id)
        bucket = grouped.setdefault(
            key,
            {
                "member_name": fact.member_name,
                "league_name": fact.league_name,
                "games_played": 0,
                "points": [],
            },
        )
        bucket["games_played"] += 1
        bucket["points"].append(fact.points)

    for (member_id, league_id), agg in grouped.items():
        session.add(
            GoldLeagueBreakdown(
                member_id=member_id,
                member_name=agg["member_name"],
                league_id=league_id,
                league_name=agg["league_name"],
                games_played=agg["games_played"],
                total_points=total_points(agg["points"]),
            )
        )

    session.commit()
    return len(grouped)


def build_gold_playoff_bracket(session: Session) -> int:
    """
    Build the playoff bracket from playoff SilverMatchupFacts, with seeds pulled
    from the already-built GoldStandings. Empty until the regular season closes.
    """
    session.execute(delete(GoldPlayoffBracket))

    seeds: dict[int, int] = {
        row.member_id: row.current_seed
        for row in session.execute(select(GoldStandings)).scalars().all()
    }
    playoff_facts = session.execute(
        select(SilverMatchupFact).where(SilverMatchupFact.is_playoff.is_(True))
    ).scalars().all()

    for fact in playoff_facts:
        session.add(
            GoldPlayoffBracket(
                round_name=fact.round_name or f"Round {fact.round_number}",
                member_a_id=fact.member_a_id,
                member_a_name=fact.member_a_name,
                member_a_seed=seeds.get(fact.member_a_id),
                member_b_id=fact.member_b_id,
                member_b_name=fact.member_b_name,
                member_b_seed=seeds.get(fact.member_b_id),
                member_a_points=fact.member_a_points,
                member_b_points=fact.member_b_points,
                winner_id=fact.winner_id,
                is_final=True,
            )
        )

    session.commit()
    return len(playoff_facts)


def build_all_gold(session: Session) -> dict[str, int]:
    """Run all silver -> gold builds in dependency order (standings before bracket)."""
    return {
        "gold_standings": build_gold_standings(session),
        "gold_member_period_scores": build_gold_member_period_scores(session),
        "gold_team_leaderboard": build_gold_team_leaderboard(session),
        "gold_league_breakdown": build_gold_league_breakdown(session),
        "gold_playoff_bracket": build_gold_playoff_bracket(session),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    args = parser.parse_args()

    engine = db_module.make_engine(args.db)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)

    with session_factory() as session:
        counts = build_all_gold(session)

    print("Gold rebuilt:")
    for table, count in counts.items():
        print(f"  {table:<28} {count:>6} rows")


if __name__ == "__main__":
    main()
