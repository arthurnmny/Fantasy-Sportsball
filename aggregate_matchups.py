"""
Monthly aggregation job.

Sums each member's SilverGameFact points for a period and compares them against
their opponent's, writing one Matchup row per pairing. This is the only place
head-to-head results are decided.

A matchup is `is_final` only once its month has fully elapsed. The period
currently in flight still gets a row with live running totals, but never a
winner -- so a live view can show the scoring race without any of it leaking
into the standings (silver only picks up final matchups).

This script also seeds the playoff bracket once the regular season completes:
top 4 by record, points as the tiebreaker, 1v4 and 2v3 in the semifinals.

Usage:
    python aggregate_matchups.py
    python aggregate_matchups.py --as-of 2026-12-31     # what the season looks like at year end
"""
from __future__ import annotations

import argparse
import calendar
from collections import defaultdict
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import db as db_module
from models import Matchup, Member, Schedule
from silver_models import SilverGameFact

PLAYOFF_SIZE = 4


def parse_as_of(raw: str | None) -> date:
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise SystemExit(f"Could not parse --as-of {raw!r}; expected YYYY-MM-DD.")


def period_end(period: str) -> date:
    """Last calendar day of a 'YYYY-MM' period."""
    year, month = (int(part) for part in period.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


def period_points(session: Session) -> dict[tuple[int, str], int]:
    """Sum silver points per (member, period) -- the whole scoring input."""
    totals: dict[tuple[int, str], int] = defaultdict(int)
    for fact in session.execute(select(SilverGameFact)).scalars().all():
        totals[(fact.member_id, fact.period)] += fact.points
    return totals


def aggregate(session: Session, as_of: date) -> int:
    """
    Rebuild every Matchup row. Returns the number of rows written.

    Bye rounds get no Matchup: there is no opponent, so there is nothing to
    resolve. The member still appears in gold's period scores, with points and
    a null result.
    """
    session.execute(delete(Matchup))
    totals = period_points(session)

    pairings = session.execute(
        select(Schedule).where(
            Schedule.member_a_id.is_not(None), Schedule.member_b_id.is_not(None)
        )
    ).scalars().all()

    rows_written = 0
    for schedule in pairings:
        a_points = totals.get((schedule.member_a_id, schedule.period), 0)
        b_points = totals.get((schedule.member_b_id, schedule.period), 0)
        is_final = period_end(schedule.period) < as_of

        winner_id: int | None = None
        if is_final and a_points != b_points:
            winner_id = schedule.member_a_id if a_points > b_points else schedule.member_b_id

        session.add(
            Matchup(
                schedule_id=schedule.id,
                member_a_points=a_points,
                member_b_points=b_points,
                winner_id=winner_id,
                is_final=is_final,
            )
        )
        rows_written += 1

    session.commit()
    return rows_written


def regular_season_records(
    session: Session,
) -> tuple[dict[int, dict[str, int]], int]:
    """
    Head-to-head records over completed regular-season matchups, plus how many
    regular-season rounds are still unresolved.
    """
    records: dict[int, dict[str, int]] = defaultdict(
        lambda: {"wins": 0, "losses": 0, "ties": 0}
    )
    matchups = session.execute(select(Matchup)).scalars().all()
    schedule_by_id = {
        s.id: s for s in session.execute(select(Schedule)).scalars().all()
    }

    pending = 0
    for matchup in matchups:
        schedule = schedule_by_id.get(matchup.schedule_id)
        if schedule is None or schedule.is_playoff:
            continue
        if not matchup.is_final:
            pending += 1
            continue
        a, b = schedule.member_a_id, schedule.member_b_id
        if a is None or b is None:
            continue
        if matchup.member_a_points > matchup.member_b_points:
            records[a]["wins"] += 1
            records[b]["losses"] += 1
        elif matchup.member_b_points > matchup.member_a_points:
            records[b]["wins"] += 1
            records[a]["losses"] += 1
        else:
            records[a]["ties"] += 1
            records[b]["ties"] += 1

    return records, pending


def seed_playoffs(session: Session) -> tuple[str, bool]:
    """
    Fill in the playoff Schedule pairings, if the prerequisites are met.

    Semifinals need the regular season complete; the final needs both
    semifinals resolved. Returns (message, whether anything changed).
    """
    playoff_rows = session.execute(
        select(Schedule)
        .where(Schedule.is_playoff.is_(True))
        .order_by(Schedule.round_number, Schedule.id)
    ).scalars().all()
    if not playoff_rows:
        return "no playoff rows in the schedule", False

    by_round: dict[int, list[Schedule]] = defaultdict(list)
    for row in playoff_rows:
        by_round[row.round_number].append(row)
    round_numbers = sorted(by_round)
    semifinals = by_round[round_numbers[0]]
    finals = by_round[round_numbers[-1]]

    changed = False
    notes: list[str] = []

    # --- Semifinals: top 4 by record, points as the tiebreaker ---
    if all(row.member_a_id and row.member_b_id for row in semifinals):
        notes.append("semifinals already seeded")
    else:
        records, pending = regular_season_records(session)
        if pending:
            return f"regular season still in progress ({pending} matchups unresolved)", False

        members = session.execute(select(Member)).scalars().all()
        season_points: dict[int, int] = defaultdict(int)
        for (member_id, _period), points in period_points(session).items():
            season_points[member_id] += points
        ranked = sorted(
            members,
            key=lambda m: (
                -records[m.id]["wins"],
                records[m.id]["losses"],
                -season_points[m.id],
            ),
        )[:PLAYOFF_SIZE]
        if len(ranked) != PLAYOFF_SIZE:
            return f"only {len(ranked)} members available to seed a {PLAYOFF_SIZE}-team bracket", False

        # Standard bracket: 1v4 and 2v3.
        pairings = [(ranked[0], ranked[3]), (ranked[1], ranked[2])]
        for row, (higher, lower) in zip(semifinals, pairings):
            row.member_a_id = higher.id
            row.member_b_id = lower.id
            changed = True
        notes.append(
            "semifinals seeded: "
            + ", ".join(f"{h.name} vs {l.name}" for h, l in pairings)
        )
        session.commit()

    # --- Final: winners of the two semifinals ---
    final_row = finals[0] if finals else None
    if final_row is not None:
        if final_row.member_a_id and final_row.member_b_id:
            notes.append("final already seeded")
        else:
            matchup_by_schedule = {
                m.schedule_id: m for m in session.execute(select(Matchup)).scalars().all()
            }
            semi_matchups = [matchup_by_schedule.get(row.id) for row in semifinals]
            if any(m is None or not m.is_final for m in semi_matchups):
                notes.append("final waiting on semifinal results")
            else:
                winners = [m.winner_id for m in semi_matchups if m is not None]
                if any(w is None for w in winners):
                    notes.append("final waiting: a semifinal ended in a tie")
                else:
                    final_row.member_a_id = winners[0]
                    final_row.member_b_id = winners[1]
                    changed = True
                    notes.append("final seeded from semifinal winners")
                    session.commit()

    return "; ".join(notes), changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    parser.add_argument(
        "--as-of",
        default=None,
        help="Treat this date as today when deciding which periods have closed (default: today)",
    )
    args = parser.parse_args()

    as_of = parse_as_of(args.as_of)
    engine = db_module.make_engine(args.db)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)

    with session_factory() as session:
        written = aggregate(session, as_of)
        message, changed = seed_playoffs(session)
        if changed:
            written = aggregate(session, as_of)

        final_count = len(
            session.execute(select(Matchup).where(Matchup.is_final.is_(True))).scalars().all()
        )

    print(f"Matchups aggregated as of {as_of}: {written} rows written")
    print(f"  resolved (period closed): {final_count}")
    print(f"  in flight / upcoming:     {written - final_count}")
    print(f"  playoffs: {message}")


if __name__ == "__main__":
    main()
