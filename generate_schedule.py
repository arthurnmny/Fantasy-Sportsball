"""
Generate the season schedule: 7 round-robin rounds, 1 bye round, 2 playoff
rounds -- one calendar month per round, March through December.

With 8 members a full round-robin needs exactly 7 rounds (28 pairings, every
member plays every other once) and mathematically requires no bye. The bye
round is kept anyway because the format calls for a rest/buffer month and it
keeps the schedule generator correct if membership ever becomes an odd number.

Playoff rounds are created as placeholders: member_a_id/member_b_id stay NULL
because the seeds are not known until the regular season ends. They are filled
in later by aggregate_matchups.resolve_playoff_pairings().

Idempotent: deletes and rebuilds the schedule (and any matchup rows hanging off
it) on every run.

Usage:
    python generate_schedule.py
    python generate_schedule.py --season-year 2027
"""
from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import db as db_module
from models import Matchup, Member, Schedule

REGULAR_ROUNDS = 7
BYE_ROUND = REGULAR_ROUNDS + 1
SEMIFINAL_ROUND = BYE_ROUND + 1
FINAL_ROUND = SEMIFINAL_ROUND + 1
TOTAL_ROUNDS = FINAL_ROUND
START_MONTH = 3
PLAYOFF_SIZE = 4


def round_robin_rounds(member_ids: list[int]) -> list[list[tuple[int, int]]]:
    """
    Circle method: fix the first member, rotate the rest one step per round.

    Produces n-1 rounds of n/2 pairings for even n -- 7 rounds of 4 for 8
    members, with every pair appearing exactly once.
    """
    if len(member_ids) % 2 != 0:
        raise SystemExit(
            f"Round-robin needs an even member count, got {len(member_ids)}. "
            "Odd counts need a per-round bye, which this generator does not do."
        )

    rotation = list(member_ids)
    rounds: list[list[tuple[int, int]]] = []
    for _ in range(len(rotation) - 1):
        half = len(rotation) // 2
        rounds.append(
            [(rotation[i], rotation[len(rotation) - 1 - i]) for i in range(half)]
        )
        # Keep the anchor fixed; rotate everyone else by one position.
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return rounds


def period_for_round(season_year: int, round_number: int) -> str:
    """Round 1 is March, round 10 is December."""
    month = START_MONTH + round_number - 1
    if month > 12:
        raise SystemExit(
            f"Round {round_number} lands in month {month}, past December. "
            "Shorten the season or start earlier."
        )
    return f"{season_year}-{month:02d}"


def build_schedule(session: Session, season_year: int, rng_seed: int) -> dict[str, int]:
    session.execute(delete(Matchup))
    session.execute(delete(Schedule))

    member_ids = [
        row for row in session.execute(select(Member.id).order_by(Member.id)).scalars().all()
    ]
    if len(member_ids) != 8:
        raise SystemExit(
            f"Expected 8 members, found {len(member_ids)}. Run seed_roster.py first."
        )

    # Shuffle who is "member 1" for the round-robin so the pairing order is not
    # simply member id order -- the circle method would otherwise put the same
    # members in the same slots every season.
    import random

    anchor = list(member_ids)
    random.Random(rng_seed).shuffle(anchor)
    rounds = round_robin_rounds(anchor)

    for round_number, pairings in enumerate(rounds, start=1):
        for member_a, member_b in pairings:
            session.add(
                Schedule(
                    period=period_for_round(season_year, round_number),
                    round_number=round_number,
                    member_a_id=member_a,
                    member_b_id=member_b,
                    is_bye=False,
                    is_playoff=False,
                    round_name=None,
                )
            )

    # Bye round: every member rests, so it is stored as one row per member with
    # no opponent. The unique constraint tolerates the NULL member_b_id.
    for member_id in member_ids:
        session.add(
            Schedule(
                period=period_for_round(season_year, BYE_ROUND),
                round_number=BYE_ROUND,
                member_a_id=member_id,
                member_b_id=None,
                is_bye=True,
                is_playoff=False,
                round_name="Bye",
            )
        )

    # Playoff placeholders. Semifinals are two pairings (top 4 -> 1v4, 2v3),
    # the final is one; all three wait on seeds.
    for index in (1, 2):
        session.add(
            Schedule(
                period=period_for_round(season_year, SEMIFINAL_ROUND),
                round_number=SEMIFINAL_ROUND,
                member_a_id=None,
                member_b_id=None,
                is_bye=False,
                is_playoff=True,
                round_name=f"Semifinal {index}",
            )
        )
    session.add(
        Schedule(
            period=period_for_round(season_year, FINAL_ROUND),
            round_number=FINAL_ROUND,
            member_a_id=None,
            member_b_id=None,
            is_bye=False,
            is_playoff=True,
            round_name="Final",
        )
    )

    session.commit()

    return {
        "regular_pairings": REGULAR_ROUNDS * (len(member_ids) // 2),
        "bye_rows": len(member_ids),
        "playoff_rows": 3,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    parser.add_argument("--season-year", type=int, default=date.today().year)
    parser.add_argument("--rng-seed", type=int, default=7, help="Seed for the pairing shuffle")
    args = parser.parse_args()

    engine = db_module.make_engine(args.db)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)

    with session_factory() as session:
        counts = build_schedule(session, args.season_year, args.rng_seed)
        rows = session.execute(select(Schedule).order_by(Schedule.round_number)).scalars().all()

    print(
        f"Schedule for {args.season_year}: {counts['regular_pairings']} round-robin pairings, "
        f"{counts['bye_rows']} bye rows, {counts['playoff_rows']} playoff placeholders "
        f"({TOTAL_ROUNDS} rounds)\n"
    )
    current_round = None
    for row in rows:
        if row.round_number != current_round:
            current_round = row.round_number
            label = row.round_name or f"Round {row.round_number}"
            print(f"  {row.period}  round {row.round_number:>2}  {label}")
        if row.is_bye:
            continue
        pairing = (
            f"{row.member_a_id} vs {row.member_b_id}"
            if row.member_a_id and row.member_b_id
            else "TBD"
        )
        print(f"                    {pairing}")


if __name__ == "__main__":
    main()
