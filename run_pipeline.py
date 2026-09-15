"""
Run the whole pipeline end to end: seed -> weights -> extract -> schedule ->
silver -> aggregate -> silver -> gold.

The order is not the obvious one, and it matters. Silver builds a matchup fact
from each finalized Matchup, but Matchup rows don't exist until the aggregation
job has run -- and the aggregation job reads SilverGameFact, which is itself a
silver build. That mutual dependency is why transform_silver.py is invoked
twice, once for each stage:

    extract -> [silver: games] -> aggregate -> [silver: derived] -> gold

Each step runs as its own process so a failure stops the run with that step's
own error message rather than a stack trace from inside the orchestrator, and
so any single step can still be re-run on its own.

Safe to re-run: every step is delete-and-rebuild, and two of them are skipped
once their output already exists.

Steps 1 and 4 -- the roster and the schedule -- build the *shape* of the season.
Neither depends on game data, both are deterministic, and once written their
output never needs regenerating to refresh results. So they are skipped when
already present, which is the normal case: a refresh runs steps 2, 3 and 5-8
only. Force them with --force (roster, wiped and re-dealt) or --reseed-schedule.

Both live in "setup files/" rather than at the root, so they are invoked by path
with PYTHONPATH pointing back here -- see SETUP_DIR.

Usage:
    python run_pipeline.py --season-start 2026-03-01 --season-end 2026-12-31
    python run_pipeline.py --season-start 2026-03-01 --season-end 2026-12-31 --force
    python run_pipeline.py --season-start 2026-03-01 --season-end 2026-12-31 --reseed-schedule
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

import db as db_module
from gold_models import GoldLeagueBreakdown, GoldStandings, GoldTeamLeaderboard
from models import OwnedTeam, Schedule
from silver_models import SilverGameFact

ROOT = Path(__file__).resolve().parent

# The one-time setup scripts live outside the repo root, which has two
# consequences and both are handled below:
#   1. they must be invoked by path, not by bare filename;
#   2. Python puts the *script's* own directory on sys.path, not the working
#      directory -- so without PYTHONPATH pointing back at the root they die with
#      "ModuleNotFoundError: No module named 'db'" before doing anything.
SETUP_DIR = ROOT / "setup files"


def setup_script(name: str) -> str:
    """Absolute path to a one-time setup script in SETUP_DIR."""
    return str(SETUP_DIR / name)


def run_step(label: str, argv: list[str], *, from_setup: bool = False) -> None:
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    env = None
    if from_setup:
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                part for part in (str(ROOT), os.environ.get("PYTHONPATH", "")) if part
            ),
        }
    completed = subprocess.run([sys.executable, *argv], env=env)
    if completed.returncode != 0:
        raise SystemExit(f"\nStep failed ({label}); stopping.")


def roster_exists(db_path: str | None) -> bool:
    """True if the roster has already been seeded."""
    engine = db_module.make_engine(db_path)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)
    with session_factory() as session:
        return session.execute(select(func.count()).select_from(OwnedTeam)).scalar_one() > 0


def schedule_exists(db_path: str | None, season_year: int) -> bool:
    """
    True if the schedule already covers this season.

    Schedule periods are 'YYYY-MM', so a prefix match on the year is enough to
    tell whether this season has been laid out.
    """
    engine = db_module.make_engine(db_path)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)
    with session_factory() as session:
        return (
            session.execute(
                select(func.count())
                .select_from(Schedule)
                .where(Schedule.period.like(f"{season_year}-%"))
            ).scalar_one()
            > 0
        )


def report(db_path: str | None) -> None:
    """Print gold standings and reconcile gold totals against silver."""
    engine = db_module.make_engine(db_path)
    session_factory = db_module.make_session_factory(engine)

    with session_factory() as session:
        standings = session.execute(
            select(GoldStandings).order_by(GoldStandings.current_seed)
        ).scalars().all()
        # Rounded to 2dp on both sides: weighted points are floats, but every
        # contributing value has at most two decimals, so rounding makes this an
        # exact equality check rather than a tolerance check.
        silver_total = round(
            session.execute(
                select(func.coalesce(func.sum(SilverGameFact.points), 0))
            ).scalar_one(),
            2,
        )
        gold_standings_total = round(sum(row.season_points for row in standings), 2)
        league_total = round(
            session.execute(
                select(func.coalesce(func.sum(GoldLeagueBreakdown.total_points), 0))
            ).scalar_one(),
            2,
        )
        team_total = round(
            session.execute(
                select(func.coalesce(func.sum(GoldTeamLeaderboard.total_points), 0))
            ).scalar_one(),
            2,
        )

    print(f"\n{'=' * 72}\nGOLD STANDINGS\n{'=' * 72}")
    print(f"{'seed':<5}{'member':<12}{'W-L-T':<10}{'pts':>9}")
    for row in standings:
        record = f"{row.wins}-{row.losses}-{row.ties}"
        print(f"{row.current_seed:<5}{row.member_name:<12}{record:<10}{row.season_points:>9.2f}")

    print(f"\n{'=' * 72}\nRECONCILIATION\n{'=' * 72}")
    print(f"  silver_game_facts.points (sum)      {silver_total:>10.2f}")
    print(f"  gold_standings.season_points (sum)  {gold_standings_total:>10.2f}")
    print(f"  gold_league_breakdown.total (sum)   {league_total:>10.2f}")
    print(f"  gold_team_leaderboard.total (sum)   {team_total:>10.2f}")

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
    parser.add_argument(
        "--reseed-schedule",
        action="store_true",
        help="Rebuild the schedule even if this season already has one (destroys every matchup)",
    )
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between ESPN requests")
    parser.add_argument("--league", default=None, help="Only extract this league (e.g. MLB)")
    args = parser.parse_args()

    # The season year comes from --season-start rather than from today's date.
    # Taking it from the clock let the two drift apart: run the 2026 season in
    # January 2027 and the extractor would pull 2026 games while the schedule
    # generator laid out March-December 2027 -- months that never overlap, so
    # every matchup would come out empty with nothing to explain why.
    try:
        season_year = date.fromisoformat(args.season_start).year
    except ValueError:
        raise SystemExit(
            f"Could not parse --season-start {args.season_start!r}; expected YYYY-MM-DD."
        )

    def with_db(argv: list[str]) -> list[str]:
        return argv + (["--db", args.db] if args.db else [])

    # seed_roster.py refuses to overwrite an existing roster without --force,
    # so calling it unconditionally would make this whole script fail on every
    # run after the first. Skip it instead, unless --force asks for a re-deal.
    if args.force:
        run_step(
            "1/8  Seed roster (top 8 per league, dealt to 8 owners)",
            with_db([setup_script("seed_roster.py"), "--seed", str(args.seed), "--force"]),
            from_setup=True,
        )
    elif args.skip_seed or roster_exists(args.db):
        print(
            "\n1/8  Seed roster -- skipped (roster already seeded; use --force to re-deal)"
        )
    else:
        run_step(
            "1/8  Seed roster (top 8 per league, dealt to 8 owners)",
            with_db([setup_script("seed_roster.py"), "--seed", str(args.seed)]),
            from_setup=True,
        )

    # Runs every time: the weights are reference data read by the silver build,
    # and re-seeding is a cheap delete-and-rebuild with no network calls.
    run_step(
        "2/8  Seed league scoring weights",
        with_db(["seed_weights.py"]),
    )

    run_step(
        "3/8  Extract results from ESPN",
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
    # The schedule is deterministic and complete the moment it is written, and
    # rebuilding it DELETEs every matchup (which step 6 then has to reconstruct).
    # So it is skipped unless this season has no schedule yet, or --reseed-schedule
    # asks for one -- e.g. after changing the bye month or the round count.
    if args.reseed_schedule or not schedule_exists(args.db, season_year):
        run_step(
            "4/8  Generate schedule",
            with_db(
                [setup_script("generate_schedule.py"), "--season-year", str(season_year)]
            ),
            from_setup=True,
        )
    else:
        print(
            f"\n4/8  Generate schedule -- skipped ({season_year} schedule already exists; "
            "use --reseed-schedule to rebuild)"
        )
    run_step(
        "5/8  Silver: game facts",
        with_db(["transform_silver.py", "--stage", "games"]),
    )
    run_step("6/8  Aggregate monthly matchups", with_db(["aggregate_matchups.py"]))
    run_step(
        "7/8  Silver: matchup facts + resolved schedule",
        with_db(["transform_silver.py", "--stage", "derived"]),
    )
    run_step("8/8  Gold aggregates", with_db(["transform_gold.py"]))

    report(args.db)


if __name__ == "__main__":
    main()
