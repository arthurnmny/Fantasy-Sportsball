"""
Apply the display names in names.py to an existing database.

Renaming a league does not require re-dealing it. `seed_roster.py --force` would
also work, but it drops every table and re-fetches all ~1800 games from ESPN to
change a label. This does the same rename with local writes only:

    1. update Member.name and OwnedTeam.team_name in bronze
    2. rebuild silver and gold, which carry those names denormalized

Nothing here touches ESPN, and no matchup result can change: names are labels,
and every score, record and standing is derived from team ids and numbers.

Members are matched to OWNER_NAMES by roster order (member 1 gets the first
name), which is the order seed_roster.py created them in. Renaming therefore
never moves a team between owners.

One thing to know about TEAM_NAMES: a team with no entry is left alone, not
reset to its ESPN name. Deleting an override therefore keeps the last name
applied. To undo a rename, point the override at the ESPN name shown in the
comment beside it in names.py.

Usage:
    python apply_names.py
    python apply_names.py --list     # show the roster and its ESPN ids
    python apply_names.py --dry-run  # report what would change, write nothing
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from sqlalchemy import select

import db as db_module
from models import League, Member, OwnedTeam
from names import OWNER_NAMES, TEAM_NAMES

# The stages that carry a denormalized name. Order matters and mirrors
# run_pipeline.py: matchups are rebuilt from the game facts, and the matchup
# facts are in turn read by gold.
REBUILD_STEPS = [
    ["transform_silver.py", "--stage", "games"],
    ["aggregate_matchups.py"],
    ["transform_silver.py", "--stage", "derived"],
    ["transform_gold.py"],
]


def list_roster(session) -> None:
    """Print every owned team with the key needed to rename it."""
    rows = session.execute(
        select(Member.name, League.name, OwnedTeam.espn_team_id, OwnedTeam.team_name)
        .join(OwnedTeam, OwnedTeam.member_id == Member.id)
        .join(League, OwnedTeam.league_id == League.id)
        .order_by(League.name, OwnedTeam.team_name)
    ).all()

    members = session.execute(select(Member).order_by(Member.id)).scalars().all()
    print(f"{len(members)} members, {len(rows)} owned teams\n")
    print(f"{'owner':<14}{'league':<8}{'espn id':<9}team")
    print("-" * 60)
    for member_name, league_name, team_id, team_name in rows:
        print(f"{member_name:<14}{league_name:<8}{team_id:<9}{team_name}")


def apply_names(session, dry_run: bool = False) -> tuple[int, int, list[str]]:
    """
    Rename members and teams from names.py. Returns (members renamed, teams
    renamed, warnings).
    """
    members = session.execute(select(Member).order_by(Member.id)).scalars().all()
    if len(members) != len(OWNER_NAMES):
        raise SystemExit(
            f"names.py lists {len(OWNER_NAMES)} owner names but the database has "
            f"{len(members)} members. They must match one-to-one -- this league "
            "is 8 owners."
        )

    members_renamed = 0
    for member, new_name in zip(members, OWNER_NAMES):
        if member.name != new_name:
            print(f"  owner   {member.name!r} -> {new_name!r}")
            if not dry_run:
                member.name = new_name
            members_renamed += 1

    owned = session.execute(
        select(OwnedTeam, League).join(League, OwnedTeam.league_id == League.id)
    ).all()

    teams_renamed = 0
    matched_keys: set[tuple[str, str]] = set()
    for team, league in owned:
        key = (league.name, team.espn_team_id)
        override = TEAM_NAMES.get(key)
        if override is None:
            continue
        matched_keys.add(key)
        if team.team_name != override:
            print(f"  team    {league.name} {team.team_name!r} -> {override!r}")
            if not dry_run:
                team.team_name = override
            teams_renamed += 1

    # A key that matches nothing is almost always a typo or a stale team id, and
    # silently ignoring it would look identical to a rename that worked.
    warnings = [
        f"{league_key} {team_id!r} matches no owned team "
        f"(check the id with --list)"
        for league_key, team_id in sorted(set(TEAM_NAMES) - matched_keys)
    ]

    if not dry_run:
        session.commit()
    return members_renamed, teams_renamed, warnings


def rebuild_dependents(db_path: str | None) -> None:
    """Re-run the stages that store names, so the change reaches the report."""
    for step in REBUILD_STEPS:
        argv = [sys.executable, *step]
        if db_path:
            argv += ["--db", db_path]
        print(f"\n  {' '.join(step)}")
        completed = subprocess.run(argv)
        if completed.returncode != 0:
            raise SystemExit(f"\nRebuild failed ({' '.join(step)}); names may be stale.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    parser.add_argument("--list", action="store_true", help="Print the roster and exit")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    engine = db_module.make_engine(args.db)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)

    with session_factory() as session:
        if args.list:
            list_roster(session)
            return

        print("Applying names from names.py\n")
        members_renamed, teams_renamed, warnings = apply_names(session, args.dry_run)

    for warning in warnings:
        print(f"  WARNING: {warning}")

    if not members_renamed and not teams_renamed:
        print("  Nothing to change -- the database already matches names.py.")
        return

    if args.dry_run:
        print(f"\nDry run: would rename {members_renamed} owners, {teams_renamed} teams.")
        return

    print(
        f"\nRenamed {members_renamed} owners and {teams_renamed} teams. "
        "Rebuilding the tables that store names..."
    )
    rebuild_dependents(args.db)
    print("\nDone. Re-run build_report.py to refresh the HTML.")


if __name__ == "__main__":
    main()
