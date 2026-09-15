"""
Seed the league_game_weights reference table from leagues.py.

Leagues play very different numbers of games per week, so raw per-game scoring
lets MLB supply 66% of all games and 47% of all points. Each league's games are
therefore scaled by NORMALIZE_TO / games_per_week, making a typical week of any
sport worth the same 10 points.

This is reference data, not derived data: the numbers come from leagues.py, are
written once, and are then read by the silver build. Nothing recomputes them
from the games in the database -- a weight that drifted with the extraction
window would silently rewrite matchups that had already been settled.

Requires the League rows to exist, so run seed_roster.py first.

Usage:
    python seed_weights.py
    python seed_weights.py --dry-run
"""
from __future__ import annotations

import argparse

from sqlalchemy import delete, select

import db as db_module
from leagues import LEAGUES
from models import League, LeagueGameWeight, NORMALIZE_TO, multiplier_for


def build_weights(session, dry_run: bool = False) -> list[tuple[str, float, float]]:
    """
    Rebuild league_game_weights. Returns (league, games_per_week, multiplier)
    rows in leagues.py order.
    """
    known = {league.name: league for league in session.execute(select(League)).scalars()}
    missing = [config.key for config in LEAGUES if config.key not in known]
    if missing:
        raise SystemExit(
            f"No League rows for: {', '.join(missing)}. Run seed_roster.py first."
        )

    if not dry_run:
        session.execute(delete(LeagueGameWeight))

    written: list[tuple[str, float, float]] = []
    for config in LEAGUES:
        league = known[config.key]
        multiplier = round(multiplier_for(config.games_per_week), 4)
        written.append((config.key, config.games_per_week, multiplier))
        if not dry_run:
            session.add(
                LeagueGameWeight(
                    league_id=league.id,
                    games_per_week=config.games_per_week,
                    multiplier=multiplier,
                    note=config.weight_note,
                )
            )

    if not dry_run:
        session.commit()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    parser.add_argument("--dry-run", action="store_true", help="Print weights without writing")
    args = parser.parse_args()

    engine = db_module.make_engine(args.db)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)

    with session_factory() as session:
        rows = build_weights(session, dry_run=args.dry_run)

    print(f"{'league':<8}{'games/wk':>10}{'multiplier':>12}{'  a win is worth':>18}")
    print("-" * 48)
    for key, games_per_week, multiplier in rows:
        print(f"{key:<8}{games_per_week:>10.2f}{multiplier:>12.2f}{multiplier:>18.2f}")
    print("-" * 48)
    print(f"Normalized so one week of any sport is worth {NORMALIZE_TO:.0f} points.")
    if args.dry_run:
        print("(dry run -- nothing written)")


if __name__ == "__main__":
    main()
