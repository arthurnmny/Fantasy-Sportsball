"""
Extract final game results from ESPN into bronze GameResult rows.

The window is a DATE window, not a season, and that is deliberate. For NBA, NHL
and NCAAB a March-December season spans two ESPN season labels (the tail of one,
the start of the next), so there is no single `season` value that covers the
window. This script asks each league for every season label that can overlap the
window, then filters the returned games to [--season-start, --season-end].

Bronze stores only what ESPN returned -- no outcome, no points. Those are
derived in silver (see transform_silver.py), which is what keeps re-introducing
spread-based scoring later free of any bronze migration.

Re-running is safe and cheap: results already stored for an (owned team, event)
pair are skipped, so a second run inserts nothing.

Usage:
    python extract_results.py --season-start 2026-03-01 --season-end 2026-12-31
    python extract_results.py --league MLB --season-start 2026-03-01 --season-end 2026-12-31
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import db as db_module
from espn_client import ClientConfig, GameRecord, games_for_team, season_params_for_window
from leagues import LEAGUES, get_league
from models import GameResult, League, OwnedTeam, local_date


def parse_day(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise SystemExit(f"Could not parse date {raw!r}; expected YYYY-MM-DD.")


def existing_keys(session: Session) -> tuple[set[tuple[int, str]], Counter]:
    """Every stored (owned_team_id, espn_event_id) pair, plus a per-team count."""
    rows = session.execute(
        select(GameResult.owned_team_id, GameResult.espn_event_id)
    ).all()
    keys = {(row[0], row[1]) for row in rows}
    return keys, Counter(row[0] for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--season-start", required=True, help="Window start, YYYY-MM-DD")
    parser.add_argument("--season-end", required=True, help="Window end, YYYY-MM-DD (inclusive)")
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    parser.add_argument("--league", default=None, help="Only extract this league (e.g. MLB)")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip owned teams that already have results. Coarse: assumes each team "
        "completes atomically, so use it to recover from an interrupted run, not to "
        "fill gaps within a team.",
    )
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between requests")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--backoff-factor", type=float, default=1.0)
    args = parser.parse_args()

    window_start = parse_day(args.season_start)
    window_end = parse_day(args.season_end)
    if window_end < window_start:
        raise SystemExit("--season-end is before --season-start.")

    engine = db_module.make_engine(args.db)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)
    client_cfg = ClientConfig(
        delay=args.delay, max_retries=args.max_retries, backoff_factor=args.backoff_factor
    )

    with session_factory() as session:
        owned = session.execute(
            select(OwnedTeam, League)
            .join(League, OwnedTeam.league_id == League.id)
            .order_by(League.name, OwnedTeam.team_name)
        ).all()
        if not owned:
            raise SystemExit("No owned teams found. Run seed_roster.py first.")
        if args.league:
            wanted = get_league(args.league).key
            owned = [(t, lg) for t, lg in owned if lg.name == wanted]
            if not owned:
                raise SystemExit(f"No owned teams for league {wanted}.")

        seen, per_team_counts = existing_keys(session)

        print(
            f"Extracting {len(owned)} owned teams over "
            f"{window_start} .. {window_end}\n"
        )

        inserted = 0
        skipped_teams = 0
        by_league: Counter = Counter()
        spanned: dict[str, tuple[datetime, datetime]] = {}
        no_games: list[tuple[str, str]] = []

        for index, (owned_team, league_row) in enumerate(owned, start=1):
            config = get_league(league_row.name)

            if args.resume and per_team_counts.get(owned_team.id):
                skipped_teams += 1
                continue

            seasons = season_params_for_window(
                window_start, window_end, config.season_year_mode
            )
            records = games_for_team(
                league_row.espn_path, owned_team.espn_team_id, seasons, client_cfg
            )
            in_window = [
                r for r in records if window_start <= local_date(r.commence_time) <= window_end
            ]
            if not records:
                # The team id resolved to nothing on the schedule endpoint, or
                # the team genuinely has no games in the requested seasons.
                # This is the real existence check for a seeded roster.
                no_games.append((league_row.name, owned_team.team_name))

            new_here = 0
            for record in in_window:
                key = (owned_team.id, record.espn_event_id)
                if key in seen:
                    continue
                seen.add(key)
                session.add(_to_game_result(owned_team.id, record))
                new_here += 1

            inserted += new_here
            by_league[league_row.name] += new_here

            if in_window:
                low = min(r.commence_time for r in in_window)
                high = max(r.commence_time for r in in_window)
                prev = spanned.get(league_row.name)
                spanned[league_row.name] = (
                    min(low, prev[0]) if prev else low,
                    max(high, prev[1]) if prev else high,
                )

            print(
                f"  [{index}/{len(owned)}] {league_row.name:<7} {owned_team.team_name:<28} "
                f"seasons={seasons} games={len(in_window):>4} new={new_here:>4}"
            )

        session.commit()
        total = session.execute(select(func.count()).select_from(GameResult)).scalar_one()

    if skipped_teams:
        print(f"\n--resume skipped {skipped_teams} owned teams that already had results.")
    if no_games:
        print(
            f"\nWARNING: {len(no_games)} owned teams returned no games at all "
            "(bad team id, or no scheduled games in those seasons):"
        )
        for league_name, team_name in no_games:
            print(f"  {league_name:<7} {team_name}")
    print(f"\nInserted {inserted} new game results.")
    print(f"game_results now holds {total} rows.\n")
    print(f"{'league':<8}{'new':>7}  window covered by data")
    for league in LEAGUES:
        low, high = spanned.get(league.key, (None, None))
        coverage = f"{low.date()} .. {high.date()}" if low else "no games in window"
        print(f"{league.key:<8}{by_league.get(league.key, 0):>7}  {coverage}")


def _to_game_result(owned_team_id: int, record: GameRecord) -> GameResult:
    return GameResult(
        owned_team_id=owned_team_id,
        espn_event_id=record.espn_event_id,
        opponent_name=record.opponent_name,
        opponent_espn_team_id=record.opponent_espn_team_id,
        team_score=record.team_score,
        opponent_score=record.opponent_score,
        commence_time=record.commence_time,
        is_home=record.is_home,
    )


if __name__ == "__main__":
    main()
