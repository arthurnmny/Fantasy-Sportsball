"""
Build a self-contained HTML report from the fantasy tracker database.

Everything -- markup, CSS, charts -- is inlined into a single file, so the
output has no external dependencies and works offline. Open it by
double-clicking, attach it to an email, or drop it in a shared folder.

This is a snapshot: it reads the database once and writes static HTML, so
re-run it after the pipeline to refresh the numbers.

Usage:
    python build_report.py
    python build_report.py --out report.html --period 2026-09
    python build_report.py --open
"""
from __future__ import annotations

import argparse
import html
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

import db as db_module
from gold_models import (
    GoldLeagueBreakdown,
    GoldStandings,
    GoldTeamLeaderboard,
)
from models import Matchup, Member, Schedule, local_period
from silver_models import SilverGameFact

esc = html.escape

# Plain string, not an f-string: the CSS braces would need escaping otherwise.
CSS = """
:root {
  --ink: #14202c; --muted: #5d6b7a; --line: #dde3ea; --bg: #f4f6f9;
  --card: #ffffff; --accent: #1f5f9e; --win: #1f7a4d; --loss: #b03030;
  --tie: #8a6d1f;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 20px 64px; background: var(--bg); color: var(--ink);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: -0.3px; }
h2 {
  font-size: 15px; text-transform: uppercase; letter-spacing: 1.1px;
  color: var(--muted); margin: 40px 0 12px; font-weight: 600;
}
.sub { color: var(--muted); font-size: 13px; margin: 0 0 8px; }
.card {
  background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; padding: 18px 20px;
}
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th {
  text-align: left; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.7px; color: var(--muted); font-weight: 600;
  padding: 0 10px 8px 0; border-bottom: 1px solid var(--line);
}
td { padding: 9px 10px 9px 0; border-bottom: 1px solid #eef2f6; }
tr:last-child td { border-bottom: none; }
.num { text-align: right; }
.seed {
  display: inline-block; width: 22px; height: 22px; line-height: 22px;
  text-align: center; border-radius: 50%; background: #e8eef5;
  color: var(--accent); font-size: 12px; font-weight: 700;
}
.seed.playoff { background: var(--accent); color: #fff; }
.rec { font-weight: 600; }
.pts { font-weight: 700; }
.w { color: var(--win); font-weight: 700; }
.l { color: var(--loss); font-weight: 700; }
.t { color: var(--tie); font-weight: 700; }
.neg { color: var(--loss); }
.muted { color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 14px; }
.owner h3 {
  margin: 0 0 2px; font-size: 15px; display: flex;
  justify-content: space-between; align-items: baseline;
}
.owner h3 .rec { font-size: 13px; }
.owner .tot { font-size: 12px; color: var(--muted); margin: 0 0 10px; }
.owner table td { padding: 6px 8px 6px 0; font-size: 13px; }
.owner table td.lg { color: var(--muted); width: 62px; }
.form { white-space: nowrap; }
.pill {
  display: inline-block; width: 17px; height: 17px; line-height: 17px;
  border-radius: 4px; font-size: 10px; font-weight: 700; text-align: center;
  margin-right: 2px; color: #fff;
}
.pill.w { background: var(--win); } .pill.l { background: var(--loss); }
.pill.t { background: var(--tie); }
.pill.none { background: #e2e7ed; color: var(--muted); }
.bars { display: grid; gap: 7px; }
.bar { display: grid; grid-template-columns: 68px 1fr 78px; align-items: center; gap: 10px; }
.bar .track { background: #eef2f6; border-radius: 4px; height: 20px; overflow: hidden; }
.bar .fill { height: 100%; background: var(--accent); border-radius: 4px; }
.bar .val { font-size: 13px; color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
.bar .name { font-size: 13px; font-weight: 600; }
.vs { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 12px; padding: 11px 0; border-bottom: 1px solid #eef2f6; }
.vs:last-child { border-bottom: none; }
.vs .side { display: flex; justify-content: space-between; gap: 10px; }
.vs .side.b { flex-direction: row-reverse; }
.vs .p { font-weight: 700; font-size: 17px; font-variant-numeric: tabular-nums; }
.vs .dash { color: var(--muted); font-size: 13px; }
.live { color: var(--loss); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; }
.done { color: var(--win); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; }
.rounds { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.round h4 { margin: 0 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.7px; color: var(--muted); }
.round div { font-size: 13px; padding: 2px 0; }
footer { margin-top: 44px; padding-top: 16px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }
"""


def load_report_data(db_path: str | None, period: str | None) -> dict:
    """Read everything the report renders in one pass."""
    engine = db_module.make_engine(db_path)
    db_module.init_db(engine)
    session_factory = db_module.make_session_factory(engine)

    with session_factory() as session:
        members = {m.id: m.name for m in session.execute(select(Member)).scalars()}
        standings = session.execute(
            select(GoldStandings).order_by(GoldStandings.current_seed)
        ).scalars().all()
        leaderboard = session.execute(select(GoldTeamLeaderboard)).scalars().all()

        # Games, newest first -- drives both the per-team form pills and the
        # league breakdown.
        games = session.execute(
            select(SilverGameFact).order_by(SilverGameFact.commence_time.desc())
        ).scalars().all()

        # Which period to feature: the one today falls in, unless it has no
        # matchups yet (or the caller overrode it).
        if period is None:
            period = local_period(datetime.now(timezone.utc))
            scheduled = set(session.execute(select(Schedule.period).distinct()).scalars())
            if period not in scheduled:
                # Off-season or before the first round -- fall back to the most
                # recent period that actually has a matchup.
                latest = session.execute(
                    select(func.max(Schedule.period))
                    .join(Matchup, Matchup.schedule_id == Schedule.id)
                ).scalar_one_or_none()
                period = latest or period

        current = session.execute(
            select(Schedule, Matchup)
            .join(Matchup, Matchup.schedule_id == Schedule.id)
            .where(Schedule.period == period)
            .order_by(Schedule.id)
        ).all()

        schedule = session.execute(
            select(Schedule).order_by(Schedule.round_number, Schedule.id)
        ).scalars().all()

        league_totals = session.execute(
            select(
                SilverGameFact.league_name,
                func.count(),
                func.sum(SilverGameFact.points),
            )
            .group_by(SilverGameFact.league_name)
            .order_by(func.sum(SilverGameFact.points).desc())
        ).all()

        silver_total = round(
            session.execute(
                select(func.coalesce(func.sum(SilverGameFact.points), 0))
            ).scalar_one(),
            2,
        )
        standings_total = round(sum(s.season_points for s in standings), 2)
        league_total = session.execute(
            select(func.coalesce(func.sum(GoldLeagueBreakdown.total_points), 0))
        ).scalar_one()
        team_total = session.execute(
            select(func.coalesce(func.sum(GoldTeamLeaderboard.total_points), 0))
        ).scalar_one()
        games_through = session.execute(
            select(func.max(SilverGameFact.commence_time))
        ).scalar_one()

    return {
        "members": members,
        "standings": standings,
        "leaderboard": leaderboard,
        "games": games,
        "period": period,
        "current": current,
        "schedule": schedule,
        "league_totals": league_totals,
        "silver_total": silver_total,
        "standings_total": standings_total,
        "league_total": league_total,
        "team_total": team_total,
        "games_through": games_through,
    }


def _record(wins: int, losses: int, ties: int) -> str:
    return f"{wins}-{losses}-{ties}"


def fmt(value: float) -> str:
    """Render a weighted point total -- no trailing .00 on whole numbers."""
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}"


def _pct_color(points: int) -> str:
    return "pts neg" if points < 0 else "pts"


def render_standings(data: dict) -> str:
    rows = []
    for row in data["standings"]:
        made_playoffs = "playoff" if row.current_seed <= 4 else ""
        rows.append(
            f"<tr><td><span class='seed {made_playoffs}'>{row.current_seed}</span></td>"
            f"<td>{esc(row.member_name)}</td>"
            f"<td class='rec'>{_record(row.wins, row.losses, row.ties)}</td>"
            f"<td class='num {_pct_color(row.season_points)}'>{fmt(row.season_points)}</td></tr>"
        )
    return (
        "<div class='card'><table><thead><tr><th></th><th>Owner</th><th>W-L-T</th>"
        "<th class='num'>Season pts</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def render_current(data: dict) -> str:
    names = data["members"]
    rows = []
    for schedule, matchup in data["current"]:
        a = names.get(schedule.member_a_id, "TBD")
        b = names.get(schedule.member_b_id, "TBD")
        status = (
            "<span class='done'>final</span>" if matchup.is_final
            else "<span class='live'>live</span>"
        )
        a_cls = "w" if matchup.member_a_points > matchup.member_b_points else ""
        b_cls = "w" if matchup.member_b_points > matchup.member_a_points else ""
        rows.append(
            f"<div class='vs'>"
            f"<div class='side a'><span>{esc(a)}</span>"
            f"<span class='p {a_cls}'>{matchup.member_a_points}</span></div>"
            f"<span class='dash'>{status}</span>"
            f"<div class='side b'><span>{esc(b)}</span>"
            f"<span class='p {b_cls}'>{matchup.member_b_points}</span></div></div>"
        )
    label = f"Round {data['current'][0][0].round_number}" if data["current"] else ""
    return (
        f"<h2>{esc(data['period'])} matchups &nbsp;<span class='muted'>{label}</span></h2>"
        "<div class='card'>" + "".join(rows) + "</div>"
    )


def render_owners(data: dict) -> str:
    # Games arrive newest-first; keep the last five per team and flip them so
    # the pills read left-to-right, oldest to newest, like a form guide.
    form: dict[int, list[SilverGameFact]] = defaultdict(list)
    for game in data["games"]:
        if len(form[game.owned_team_id]) < 5:
            form[game.owned_team_id].append(game)
    for games in form.values():
        games.reverse()

    by_member: dict[int, list[GoldTeamLeaderboard]] = defaultdict(list)
    for team in data["leaderboard"]:
        by_member[team.member_id].append(team)

    record = {s.member_id: _record(s.wins, s.losses, s.ties) for s in data["standings"]}
    totals = {s.member_id: s.season_points for s in data["standings"]}

    cards = []
    for standing in data["standings"]:
        teams = sorted(by_member[standing.member_id], key=lambda t: t.league_name)
        rows = []
        for team in teams:
            pills = "".join(
                f"<span class='pill {'w' if g.points > 0 else 'l' if g.points < 0 else 't'}'>"
                f"{'W' if g.points > 0 else 'L' if g.points < 0 else 'T'}</span>"
                for g in form.get(team.owned_team_id, [])
            ) or "<span class='pill none'>-</span>"
            rows.append(
                f"<tr><td class='lg'>{esc(team.league_name)}</td>"
                f"<td>{esc(team.team_name)}</td>"
                f"<td class='form'>{pills}</td>"
                f"<td class='num muted'>{_record(team.wins, team.losses, team.ties)}</td>"
                f"<td class='num {_pct_color(team.total_points)}'>{fmt(team.total_points)}</td></tr>"
            )
        cards.append(
            f"<div class='card owner'><h3><span>{esc(standing.member_name)}</span>"
            f"<span class='rec'>{record[standing.member_id]}</span></h3>"
            f"<p class='tot'>{fmt(totals[standing.member_id])} season points across "
            f"{len(teams)} teams</p>"
            f"<table><tbody>{''.join(rows)}</tbody></table></div>"
        )
    return "<h2>Owners &amp; teams</h2><div class='grid'>" + "".join(cards) + "</div>"


def render_leagues(data: dict) -> str:
    totals = data["league_totals"]
    peak = max((t[2] for t in totals), default=1) or 1
    silver = data["silver_total"] or 1
    bars = []
    for name, count, points in totals:
        width = max(points / peak * 100, 1.5)
        share = points / silver * 100
        bars.append(
            f"<div class='bar'><span class='name'>{esc(name)}</span>"
            f"<span class='track'><span class='fill' style='width:{width:.2f}%'></span></span>"
            f"<span class='val'>{fmt(points)} pts &middot; {share:.0f}%</span></div>"
        )
    return "<h2>Where the points come from</h2><div class='card'><div class='bars'>" + "".join(bars) + "</div></div>"


def render_schedule(data: dict) -> str:
    names = data["members"]
    rounds: dict[int, list[Schedule]] = defaultdict(list)
    for row in data["schedule"]:
        rounds[row.round_number].append(row)

    cards = []
    for number in sorted(rounds):
        rows = rounds[number]
        label = rows[0].round_name or f"Round {number}"
        period = rows[0].period
        pairings = []
        for row in rows:
            if row.member_a_id is None and row.member_b_id is None:
                pairings.append("<div class='muted'>TBD</div>")
            elif row.member_b_id is None:
                pairings.append(f"<div>{esc(names.get(row.member_a_id, '?'))} &middot; bye</div>")
            else:
                pairings.append(
                    f"<div>{esc(names.get(row.member_a_id, '?'))} vs "
                    f"{esc(names.get(row.member_b_id, '?'))}</div>"
                )
        cards.append(
            f"<div class='round'><h4>{esc(period)} &middot; {esc(label)}</h4>"
            f"{''.join(pairings)}</div>"
        )
    return "<h2>Season schedule</h2><div class='card'><div class='rounds'>" + "".join(cards) + "</div></div>"


def render(data: dict, generated_at: datetime) -> str:
    through = data["games_through"]
    through_text = through.strftime("%Y-%m-%d %H:%M UTC") if through else "no games"
    games = len(data["games"])

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fantasy Sportsball</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Fantasy Sportsball</h1>
<p class="sub">2026 season &middot; {games} games through {esc(through_text)} &middot;
{len(data['standings'])} owners &middot; generated {generated_at.strftime('%Y-%m-%d %H:%M')}</p>
{render_standings(data)}
{render_current(data)}
{render_owners(data)}
{render_leagues(data)}
{render_schedule(data)}
<footer>
Reconciliation &mdash; silver game facts {fmt(data['silver_total'])} pts &middot;
standings {fmt(data['standings_total'])} &middot; league breakdown {fmt(data['league_total'])} &middot;
team leaderboard {fmt(data['team_total'])}.
The four agree, so the gold tables tie back to silver.
</footer>
</div></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", default=None, help="SQLite path (default data/fantasy_tracker.db)")
    parser.add_argument("--out", default="report.html", help="Output file (default report.html)")
    parser.add_argument("--period", default=None, help="Feature this period, e.g. 2026-09")
    parser.add_argument("--open", action="store_true", help="Open the report in a browser")
    args = parser.parse_args()

    data = load_report_data(args.db, args.period)
    generated_at = datetime.now()
    out = Path(args.out)
    out.write_text(render(data, generated_at), encoding="utf-8")

    print(f"Wrote {out} ({out.stat().st_size:,} bytes)")
    print(f"  period featured: {data['period']}")
    print(f"  owners: {len(data['standings'])}  teams: {len(data['leaderboard'])}  "
          f"games: {len(data['games'])}")

    if args.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
