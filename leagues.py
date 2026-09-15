"""
The 7-league configuration table.

This is the one place to edit when a league's ranking source or season
semantics change -- e.g. flipping a league from prior-season to current-season
standings once its season is underway. Nothing else hardcodes a league.

Field notes
-----------
`season_year_mode` encodes how ESPN labels a season, which differs by league
and is the subtlest trap in this dataset:

  "starting" -- a season labelled Y is played within calendar year Y
                (NFL, MLB, NCAAF, MLS).
  "ending"   -- a season labelled Y runs autumn Y-1 through spring Y, so it is
                indexed by the year it *ends* in (NBA, NHL, NCAAB).

So `season=2026` means fall 2026 for MLB but the 2025-26 season for the NBA.
Combined with this season's March-December window, the "ending" leagues each
span two ESPN season labels -- see espn_client.season_params_for_window.

`seed_season` is the season whose final ranking seeds the roster. Where a
league's current season has not meaningfully started, this points at the last
completed one, because a live table with three games played is noise.

`games_per_week` is the scoring weight input: how many games one team typically
plays in a week. Points are scaled by NORMALIZE_TO / games_per_week (see
models.py), so a week of any sport is worth the same 10 points. Edit a value
here, re-run seed_weights.py, and rebuild silver -- nothing else hardcodes a
weight.

Two provenances are in play, noted per league. "Observed" means the rate was
measured from games already in the database, over a window that covers a
representative slice of that league's season. "Arithmetic" means the observed
window was unrepresentative -- a few weeks of playoff push, or a tournament --
so the rate comes from full-season games divided by season length in weeks.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LeagueConfig:
    key: str
    espn_path: str
    # "standings" -- rank by a standings stat. "poll" -- rank by the AP poll
    # (college football publishes no cross-conference standings metric).
    ranking_source: str
    # Which standings stat to sort by, descending. "points" for the two
    # soccer/hockey tables that rank on points rather than win percentage.
    sort_stat: str | None
    seed_season: int | None
    season_year_mode: str
    note: str
    # Typical games one team plays per week. Drives this league's scoring
    # weight (models.multiplier_for).
    games_per_week: float
    # Where that number came from -- copied into league_game_weights.note.
    weight_note: str


LEAGUES: tuple[LeagueConfig, ...] = (
    LeagueConfig(
        key="NFL",
        espn_path="football/nfl",
        ranking_source="standings",
        sort_stat="winPercent",
        seed_season=2025,
        season_year_mode="starting",
        note="2026 season is 1 game old -- seeded from the last completed season.",
        games_per_week=1.0,
        weight_note="Observed 1.00 -- 17 games over an 18-week season.",
    ),
    LeagueConfig(
        key="NBA",
        espn_path="basketball/nba",
        ranking_source="standings",
        sort_stat="winPercent",
        seed_season=2026,  # the 2025-26 season, which ended in June
        season_year_mode="ending",
        note="Between seasons -- seeded from the completed 2025-26 season.",
        games_per_week=3.4,
        weight_note=(
            "Arithmetic 3.4 -- 82 games over ~24 weeks. Not observed: the window "
            "only catches the spring playoff push (7 weeks, 3.20/wk), which runs "
            "hotter than a normal stretch."
        ),
    ),
    LeagueConfig(
        key="MLB",
        espn_path="baseball/mlb",
        ranking_source="standings",
        sort_stat="winPercent",
        seed_season=2026,
        season_year_mode="starting",
        note="Current season, in progress.",
        games_per_week=6.0,
        weight_note="Observed 5.99 -- 25 weeks in-window, a representative slice.",
    ),
    LeagueConfig(
        key="NHL",
        espn_path="hockey/nhl",
        ranking_source="standings",
        sort_stat="points",
        seed_season=2026,  # the 2025-26 season, which ended in April
        season_year_mode="ending",
        note="Between seasons -- seeded from the completed 2025-26 season.",
        games_per_week=3.4,
        weight_note=(
            "Arithmetic 3.4 -- 82 games over ~24 weeks. Not observed: the window "
            "only catches the spring playoff push (7 weeks, 3.23/wk)."
        ),
    ),
    LeagueConfig(
        key="NCAAF",
        espn_path="football/college-football",
        ranking_source="poll",
        sort_stat=None,
        seed_season=None,
        season_year_mode="starting",
        note="Standings cannot rank across conferences -- seeded from the AP Top 25.",
        games_per_week=1.0,
        weight_note="Observed 1.00 -- 12 games over a 13-week season.",
    ),
    LeagueConfig(
        key="NCAAB",
        espn_path="basketball/mens-college-basketball",
        ranking_source="poll",
        sort_stat=None,
        seed_season=None,
        season_year_mode="ending",
        note=(
            "Offseason; seeded from the final AP Top 25 of the completed 2025-26 season. "
            "Not standings: with 360+ D1 teams on wildly uneven schedules, winPercent "
            "surfaces mid-majors with inflated records (High Point, Miami OH) rather than "
            "the strongest teams."
        ),
        games_per_week=1.7,
        weight_note=(
            "Arithmetic 1.7 -- 31 games over an 18-week regular season. Not "
            "observed: the window only catches the NCAA tournament (2.1 weeks, "
            "2.29/wk), which is not a typical week."
        ),
    ),
    LeagueConfig(
        key="MLS",
        espn_path="soccer/usa.1",
        ranking_source="standings",
        sort_stat="points",
        seed_season=2026,
        season_year_mode="starting",
        note="Current season, in progress; ranked by points.",
        games_per_week=1.25,
        weight_note="Observed 1.25 -- 18.5 weeks in-window, includes midweek fixtures.",
    ),
)


LEAGUES_BY_KEY: dict[str, LeagueConfig] = {c.key: c for c in LEAGUES}


def get_league(key: str) -> LeagueConfig:
    try:
        return LEAGUES_BY_KEY[key]
    except KeyError:
        raise SystemExit(
            f"Unknown league {key!r}. Known leagues: {', '.join(LEAGUES_BY_KEY)}"
        )
