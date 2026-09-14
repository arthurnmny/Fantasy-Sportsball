"""
Gold layer: dashboard-ready aggregates. One row per "thing the dashboard
displays" -- built entirely from silver, so the dashboard does zero joining
or math at query time. These tables are rebuilt on each run, not append-only.

The cover columns (`covers`, `cover_rate`) are gone along with the odds capture
job. Everything here now derives from final scores alone.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class GoldStandings(Base):
    """One row per member -- current record, season point total, playoff seed."""

    __tablename__ = "gold_standings"

    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), primary_key=True)
    member_name: Mapped[str] = mapped_column(String(100), nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ties: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Cumulative points across every game played this season, including the
    # period currently in flight -- used as the seeding tiebreaker, not the
    # primary standings sort (that's the head-to-head record).
    season_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<GoldStandings {self.member_name} {self.wins}-{self.losses}-{self.ties}>"


class GoldMemberPeriodScore(Base):
    """One row per member per month -- feeds the score-over-time trend chart."""

    __tablename__ = "gold_member_period_scores"
    __table_args__ = (
        UniqueConstraint("member_id", "period", name="uq_gold_member_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    points_scored: Mapped[int] = mapped_column(Integer, nullable=False)
    opponent_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    # 'win' | 'loss' | 'tie' | null (period still in flight, or a bye round)
    matchup_result: Mapped[str | None] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<GoldMemberPeriodScore member={self.member_id} {self.period} pts={self.points_scored}>"


class GoldTeamLeaderboard(Base):
    """One row per owned team for the season -- answers 'which team is carrying me.'"""

    __tablename__ = "gold_team_leaderboard"

    owned_team_id: Mapped[int] = mapped_column(ForeignKey("owned_teams.id"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    member_name: Mapped[str] = mapped_column(String(100), nullable=False)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    league_name: Mapped[str] = mapped_column(String(50), nullable=False)
    team_name: Mapped[str] = mapped_column(String(150), nullable=False)

    games_played: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ties: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<GoldTeamLeaderboard {self.team_name} ({self.member_name}) pts={self.total_points}>"


class GoldLeagueBreakdown(Base):
    """One row per (member, league) -- answers 'is my score coming from my NBA team or my NFL team.'"""

    __tablename__ = "gold_league_breakdown"
    __table_args__ = (
        UniqueConstraint("member_id", "league_id", name="uq_gold_league_breakdown"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    member_name: Mapped[str] = mapped_column(String(100), nullable=False)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    league_name: Mapped[str] = mapped_column(String(50), nullable=False)
    games_played: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<GoldLeagueBreakdown {self.member_name}/{self.league_name} pts={self.total_points}>"


class GoldPlayoffBracket(Base):
    """
    One row per playoff matchup -- seeds, pairing, result. Empty until the
    regular season completes and resolve_playoff_pairings() seeds the bracket.
    """

    __tablename__ = "gold_playoff_bracket"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_name: Mapped[str] = mapped_column(String(50), nullable=False)  # "Semifinal", "Final", ...
    member_a_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    member_a_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    member_a_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    member_b_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    member_b_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    member_b_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    member_a_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    member_b_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    is_final: Mapped[bool] = mapped_column(default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<GoldPlayoffBracket {self.round_name} a={self.member_a_name} b={self.member_b_name}>"
