"""
Run the whole pipeline end to end: seed -> extract -> schedule -> silver ->
aggregate -> silver -> gold.

The order is not the obvious one, and it matters. Silver builds a matchup fact
from each finalized Matchup, but Matchup rows don't exist until the aggregation
job has run -- and the aggregation job reads SilverGameFact, which is itself a
silver build. That mutual dependency is why transform_silver.py is invoked
twice, once for each stage:

    extract -> [silver: games] -> aggregate -> [silver: derived] -> gold

Each step runs as its own process so a failure stops the run with that step's
own error message rather than a stack trace from inside the orchestrator, and
so any single step can still be re-run on its own.

Usage:
    python run_pipeline.py --season-start 2026-03-01 --season-end 2026-12-31
    python run_pipeline.py --season-start 2026-03-01 --season-end 2026-12-31 --force
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from sqlalchemy import func, select

import db as db_module
from gold_models import GoldLeagueBreakdown, GoldStandings, GoldTeamLeaderboard
from silver_models import SilverGameFact


def run_step(label: str, argv: list[str]) -> None:
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    completed = subprocess.run([sys.executable, *argv])
    if completed.returncode != 0:
        raise SystemExit(f"\nStep failed ({label}); stopping.")


def report(db_path: str | None) -> None:
    """Print gold standings and reconcile gold totals against silver."""
    engine = db_module.make_engine(db_path)
    session_factory = db_module.make_session_factory(engine)

    with session_factory() as session:
        standings = session.execute(
            select(GoldStandings).order_by(GoldStandings.current_seed)
        ).scalars().all()
        silver_total = session.execute(
            select(func.coalesce(func.sum(SilverGameFact.points), 0))
        ).scalar_one()
        gold_standings_total = sum(row.season_points for row in standings)
        league_total = session.execute(
            select(func.coalesce(func.sum(GoldLeagueBreakdown.total_points), 0))
        ).scalar_one()
        team_total = session.execute(
            select(func.coalesce(func.sum(GoldTeamLeaderboard.total_points), 0))
        ).scalar_one()

    print(f"\n{'=' * 72}\nGOLD STANDINGS\n{'=' * 72}")
    print(f"{'seed':<5}{'member':<12}{'W-L-T':<10}{'pts':>7}")
    for row in standings:
        record = f"{row.wins}-{row.losses}-{row.ties}"
        print(f"{row.current_seed:<5}{row.member_name:<12}{record:<10}{row.season_points:>7}")

    print(f"\n{'=' * 72}\nRECONCILIATION\n{'=' * 72}")
    print(f"  silver_game_facts.points (sum)      {silver_total:>8}")
    print(f"  gold_standings.season_points (sum)  {gold_standings_total:>8}")
    print(f"  gold_league_breakdown.total (sum)   {league_total:>8}")
    print(f"  gold_team_leaderboard.total (sum)   {team_total:>8}")

    checks = {
        "standings match silver": gold_standings_total == silver_total,
        "league breakdown matches silver": league_total == silver_total,
        "team leaderboard matches silver": team_total == silver_total,
    }
    for label, ok in checks.items():
        print(f"  [{'ok' if ok else 'FAIL'}] {label}")
    if not all(checks.values()):
        raise SystemExit("Reconciliation failed -- gold does not tie back to silver.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--season-start", required=True, help="Window start, YYYY-MM-DD")
    parser.add_argument("--season-end", required=True, help="Window end, YYYY-MM-DD")
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for the roster deal")
    parser.add_argument("--force", action="store_true", help="Wipe the database and reseed the roster")
    parser.add_argument("--skip-seed", action="store_true", help="Assume the roster already exists")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between ESPN requests")
    parser.add_argument("--league", default=None, help="Only extract this league (e.g. MLB)")
    args = parser.parse_args()

    def with_db(argv: list[str]) -> list[str]:
        return argv + (["--db", args.db] if args.db else [])

    if not args.skip_seed:
        seed_argv = ["seed_roster.py", "--seed", str(args.seed)]
        if args.force:
            seed_argv.append("--force")
        run_step("1/7  Seed roster (top 8 per league, dealt to 8 owners)", with_db(seed_argv))

    run_step(
        "2/7  Extract results from ESPN",
        with_db(
            [
                "extract_results.py",
                "--season-start",
                args.season_start,
                "--season-end",
                args.season_end,
                "--delay",
                str(args.delay),
            ]
            + (["--league", args.league] if args.league else [])
        ),
    )
    run_step("3/7  Generate schedule", with_db(["generate_schedule.py"]))
    run_step(
        "4/7  Silver: game facts",
        with_db(["transform_silver.py", "--stage", "games"]),
    )
    run_step("5/7  Aggregate monthly matchups", with_db(["aggregate_matchups.py"]))
    run_step(
        "6/7  Silver: matchup facts + resolved schedule",
        with_db(["transform_silver.py", "--stage", "derived"]),
    )
    run_step("7/7  Gold aggregates", with_db(["transform_gold.py"]))

    report(args.db)


if __name__ == "__main__":
    main()
