"""
Database models -- bronze layer.

Bronze holds raw, source-shaped facts: one row per (owned team, ESPN event),
with no scoring logic baked in. `outcome` and `points` are deliberately absent
here -- they are derived in silver (see silver_models.SilverGameFact) so that
re-introducing spread-based scoring later needs no bronze migration.

Season shape (see fantasy-tracker-scope.md):
- 8 members, each owning one team per league across 7 leagues (56 OwnedTeams).
- 10 monthly rounds: 7 round-robin + 1 bye + 2 playoff rounds (semifinal, final).
- Season runs March -> December.
- Scoring per game: loss=-1, tie=0, win=+1, scaled by a per-league weight.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# All 7 leagues are North American and matchup periods are calendar months, so
# every game has to be assigned to a month in *some* local timezone. UTC is the
# wrong choice: a 7pm Pacific game on the last day of a month lands after
# midnight UTC and would bucket into the following month (25 games in the 2026
# window do exactly that). US Eastern is the latest US zone, so it never moves a
# game earlier than its venue's own local date, while still pulling the late
# West Coast games back onto the correct day.
LEAGUE_TZ = ZoneInfo("America/New_York")


def local_date(commence_time: datetime) -> date:
    """Calendar date of a naive-UTC commence time, in league-local time."""
    if commence_time.tzinfo is None:
        commence_time = commence_time.replace(tzinfo=timezone.utc)
    return commence_time.astimezone(LEAGUE_TZ).date()


def local_period(commence_time: datetime) -> str:
    """The 'YYYY-MM' fantasy period a game belongs to."""
    return local_date(commence_time).strftime("%Y-%m")


class Outcome(str, enum.Enum):
    LOSS = "loss"
    TIE = "tie"
    WIN = "win"


# Single source of truth for scoring. Spread-based tiers (push, win-and-cover)
# were removed along with the odds capture job -- if they come back, they belong
# in this table and nowhere else.
POINTS_BY_OUTCOME: dict[Outcome, int] = {
    Outcome.LOSS: -1,
    Outcome.TIE: 0,
    Outcome.WIN: 1,
}


def outcome_from_scores(team_score: int, opponent_score: int) -> Outcome:
    """Classify a final score into an Outcome."""
    if team_score > opponent_score:
        return Outcome.WIN
    if team_score < opponent_score:
        return Outcome.LOSS
    return Outcome.TIE


def points_for_scores(team_score: int, opponent_score: int) -> tuple[Outcome, int]:
    """Return (outcome, unweighted points) for a final score."""
    outcome = outcome_from_scores(team_score, opponent_score)
    return outcome, POINTS_BY_OUTCOME[outcome]


# Leagues play wildly different numbers of games per week -- an MLB team plays
# about six times a week, an NFL team once. Left alone, MLB supplies 66% of all
# games and therefore 47% of all points, and the fantasy league becomes a
# baseball contest with six side bets.
#
# So one game is scaled by NORMALIZE_TO / games_per_week, which makes a typical
# week of any sport worth the same NORMALIZE_TO points: an NFL win is worth 10,
# an MLB win about 1.67. See LeagueGameWeight for the per-league values.
NORMALIZE_TO = 10.0


def multiplier_for(games_per_week: float) -> float:
    """Scale one game so a week of that league is worth NORMALIZE_TO points."""
    if games_per_week <= 0:
        raise ValueError(f"games_per_week must be positive, got {games_per_week!r}")
    return NORMALIZE_TO / games_per_week


def weighted_points(raw_points: int, multiplier: float) -> float:
    """
    Apply a league's game weight.

    Rounded to 2dp per game so every stored value has at most two decimals and
    any sum of them is exactly representable -- which keeps the gold-vs-silver
    reconciliation an equality check rather than a tolerance check.
    """
    return round(raw_points * multiplier, 2)


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    owned_teams: Mapped[list["OwnedTeam"]] = relationship(
        back_populates="member", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Member id={self.id} name={self.name!r}>"


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    # ESPN path segment, e.g. "football/nfl", "basketball/mens-college-basketball".
    # Combined with a base URL in espn_client.py to build every endpoint.
    espn_path: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # Which ranking method produced this league's roster, for auditability.
    ranking_source: Mapped[str] = mapped_column(String(50), nullable=False)

    owned_teams: Mapped[list["OwnedTeam"]] = relationship(back_populates="league")

    def __repr__(self) -> str:
        return f"<League id={self.id} name={self.name!r}>"


class LeagueGameWeight(Base):
    """
    Reference table: what one game is worth in each league, one row per league.

    `multiplier` is NORMALIZE_TO / games_per_week, so a typical week of any
    sport is worth the same 10 points. Seeded from leagues.py by
    seed_weights.py; nothing computes these on the fly.

    Deliberately fixed inputs rather than a value derived from the games in the
    database: a weight recomputed on each run would drift as extraction windows
    changed, silently rewriting matchups that had already been settled.
    """

    __tablename__ = "league_game_weights"

    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), primary_key=True
    )
    # Typical games one team plays in a week -- the input to the weight.
    games_per_week: Mapped[float] = mapped_column(Float, nullable=False)
    # NORMALIZE_TO / games_per_week, stored rather than derived so the applied
    # weight is auditable after the fact.
    multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    # Where games_per_week came from -- observed rate vs season arithmetic.
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    league: Mapped["League"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<LeagueGameWeight league_id={self.league_id} "
            f"gpw={self.games_per_week} x{self.multiplier}>"
        )


class OwnedTeam(Base):
    """One (member, league) pair -- 56 rows once the draft is fully seeded."""

    __tablename__ = "owned_teams"
    __table_args__ = (
        UniqueConstraint("member_id", "league_id", name="uq_member_one_team_per_league"),
        UniqueConstraint("league_id", "team_name", name="uq_team_owned_once_per_league"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    team_name: Mapped[str] = mapped_column(String(150), nullable=False)
    # ESPN's stable numeric team id (stored as text -- it is an opaque key, not
    # a number we ever do arithmetic on).
    espn_team_id: Mapped[str] = mapped_column(String(50), nullable=False)

    member: Mapped["Member"] = relationship(back_populates="owned_teams")
    league: Mapped["League"] = relationship(back_populates="owned_teams")
    game_results: Mapped[list["GameResult"]] = relationship(
        back_populates="owned_team", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<OwnedTeam id={self.id} team={self.team_name!r} member_id={self.member_id}>"


class GameResult(Base):
    """
    One final game, from the perspective of one owned team.

    Carries no `outcome`/`points` -- those are derived in silver from the two
    scores, so bronze stays a faithful copy of what ESPN returned.
    """

    __tablename__ = "game_results"
    __table_args__ = (
        UniqueConstraint("owned_team_id", "espn_event_id", name="uq_result_per_team_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owned_team_id: Mapped[int] = mapped_column(ForeignKey("owned_teams.id"), nullable=False)
    espn_event_id: Mapped[str] = mapped_column(String(50), nullable=False)
    opponent_name: Mapped[str] = mapped_column(String(150), nullable=False)
    opponent_espn_team_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    team_score: Mapped[int] = mapped_column(Integer, nullable=False)
    opponent_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # Kickoff/first pitch, naive UTC. Named `commence_time` rather than
    # `game_date` because it carries a time, and the date alone is not enough
    # to order games within a day.
    commence_time: Mapped[datetime] = mapped_column(nullable=False)
    is_home: Mapped[bool] = mapped_column(default=False, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    owned_team: Mapped["OwnedTeam"] = relationship(back_populates="game_results")

    def __repr__(self) -> str:
        return (
            f"<GameResult team_id={self.owned_team_id} "
            f"{self.team_score}-{self.opponent_score} event={self.espn_event_id}>"
        )


class Schedule(Base):
    """
    One row per (round, pairing) for the whole season: 7 round-robin rounds,
    1 bye round, 2 playoff rounds (semifinal, final). Generated once per season.

    Playoff rows are created with member_a_id/member_b_id NULL -- the seeds are
    not known until the regular season ends, and are filled in later by
    aggregate_matchups.resolve_playoff_pairings().
    """

    __tablename__ = "schedule"
    __table_args__ = (
        UniqueConstraint("round_number", "member_a_id", "member_b_id", name="uq_schedule_pairing"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # "2026-03" .. "2026-12" -- one calendar month per round, March through December.
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-10
    member_a_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    # Nullable: a bye round pairs a member against no one, and a playoff round
    # has no members until seeding resolves.
    member_b_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    is_bye: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_playoff: Mapped[bool] = mapped_column(default=False, nullable=False)
    # e.g. "Semifinal", "Final" -- null for regular-season rounds.
    round_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    member_a: Mapped["Member | None"] = relationship(foreign_keys=[member_a_id])
    member_b: Mapped["Member | None"] = relationship(foreign_keys=[member_b_id])
    matchup: Mapped["Matchup | None"] = relationship(
        back_populates="schedule_entry", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Schedule round={self.round_number} period={self.period} a={self.member_a_id} b={self.member_b_id}>"


class Matchup(Base):
    """
    Resolved result of one Schedule pairing: each member's summed SilverGameFact
    points for that period, and the winner.

    Written by the monthly aggregation job (aggregate_matchups.py) after a
    period closes. `is_final` is False for the period currently in flight, so a
    live view can show running totals that never land in the standings.
    """

    __tablename__ = "matchups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Cascade: a matchup is meaningless once its schedule pairing is gone, and
    # generate_schedule.py rebuilds the whole schedule on every run.
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("schedule.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # Float, not Integer: a weighted game can be worth 1.67 or 2.94 points.
    member_a_points: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    member_b_points: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    # Null until resolved, always null for a bye round, and null for a period
    # that is still in flight.
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    is_final: Mapped[bool] = mapped_column(default=False, nullable=False)

    schedule_entry: Mapped["Schedule"] = relationship(back_populates="matchup")
    winner: Mapped["Member | None"] = relationship(foreign_keys=[winner_id])

    def __repr__(self) -> str:
        return (
            f"<Matchup schedule_id={self.schedule_id} "
            f"{self.member_a_points}-{self.member_b_points} winner_id={self.winner_id}>"
        )
