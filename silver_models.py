"""
Silver layer: bronze data cleaned, conformed, and joined to a consistent grain.
Still one row per real-world event (a game, a matchup) -- not yet rolled up into
dashboard aggregates. That's the gold layer's job.

Three things are true here that were not true in the odds-era design:

0. `points` is *weighted*: the raw -1/0/+1 is scaled by the league's
   game weight (models.LeagueGameWeight) so that a week of MLB is worth the
   same as a week of NFL. `raw_points` keeps the unweighted value alongside it.

1. `outcome` and `points` are *derived in this layer* from the raw score, not
   copied from bronze. Bronze stores only what ESPN returned.
2. There is no `is_valid` flag. It existed to cross-check bronze's stored
   outcome against a re-derived one; now that the derivation happens here, there
   is nothing left to check against. It returns with the odds work, where it
   would genuinely validate cover math against a stored spread.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from models import Base, Outcome


class SilverGameFact(Base):
    """
    One row per (owned team, game) -- GameResult + OwnedTeam + Member + League
    flattened into a single row, with the scoring rule applied, so the dashboard
    never has to join four bronze tables to answer "how did Bob's Lakers do in
    April."
    """

    __tablename__ = "silver_game_facts"
    __table_args__ = (
        UniqueConstraint("source_result_id", name="uq_silver_game_fact_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Lineage back to bronze -- always keep a path to the raw source.
    # ON DELETE CASCADE because a silver fact cannot outlive its source: the
    # bronze delete-and-rebuild pattern would otherwise fail the FK check on any
    # re-run. Rebuilt immediately after by transform_silver.py.
    source_result_id: Mapped[int] = mapped_column(
        ForeignKey("game_results.id", ondelete="CASCADE"), nullable=False
    )

    owned_team_id: Mapped[int] = mapped_column(ForeignKey("owned_teams.id"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    member_name: Mapped[str] = mapped_column(String(100), nullable=False)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    league_name: Mapped[str] = mapped_column(String(50), nullable=False)
    team_name: Mapped[str] = mapped_column(String(150), nullable=False)
    opponent_name: Mapped[str] = mapped_column(String(150), nullable=False)

    commence_time: Mapped[datetime] = mapped_column(nullable=False)
    # "2026-03" .. "2026-12" -- derived from commence_time, used to bucket into
    # matchup periods.
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    is_home: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    team_score: Mapped[int] = mapped_column(Integer, nullable=False)
    opponent_score: Mapped[int] = mapped_column(Integer, nullable=False)

    # Derived here from the scores -- see models.outcome_from_scores.
    outcome: Mapped[Outcome] = mapped_column(Enum(Outcome), nullable=False)
    # The unweighted -1/0/+1, kept so a weighted total can always be traced back
    # to the raw result that produced it.
    raw_points: Mapped[int] = mapped_column(Integer, nullable=False)
    # The league's weight at the time this fact was built, copied rather than
    # joined so a later edit to league_game_weights cannot retroactively change
    # what an already-settled matchup was scored against.
    weight_applied: Mapped[float] = mapped_column(Float, nullable=False)
    # raw_points * weight_applied, rounded to 2dp. What everything downstream sums.
    points: Mapped[float] = mapped_column(Float, nullable=False)

    built_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<SilverGameFact {self.member_name}/{self.team_name} {self.period} pts={self.points}>"


class SilverMatchupFact(Base):
    """One row per resolved Schedule pairing, with both members' names and margin added."""

    __tablename__ = "silver_matchup_facts"
    __table_args__ = (
        UniqueConstraint("source_matchup_id", name="uq_silver_matchup_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_matchup_id: Mapped[int] = mapped_column(
        ForeignKey("matchups.id", ondelete="CASCADE"), nullable=False
    )
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("schedule.id", ondelete="CASCADE"), nullable=False
    )

    period: Mapped[str] = mapped_column(String(7), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_playoff: Mapped[bool] = mapped_column(Boolean, nullable=False)
    round_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    member_a_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    member_a_name: Mapped[str] = mapped_column(String(100), nullable=False)
    member_a_points: Mapped[float] = mapped_column(Float, nullable=False)

    member_b_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    member_b_name: Mapped[str] = mapped_column(String(100), nullable=False)
    member_b_points: Mapped[float] = mapped_column(Float, nullable=False)

    winner_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    winner_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    margin: Mapped[float] = mapped_column(Float, nullable=False)  # abs(a_points - b_points)

    built_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<SilverMatchupFact {self.member_a_name} vs {self.member_b_name} {self.period}>"


class SilverScheduleResolved(Base):
    """
    Schedule with pairings filled in. Bronze Schedule rows for playoff rounds
    start with member_a_id/member_b_id NULL until the regular season ends --
    this table only ever holds fully-resolved rows.
    """

    __tablename__ = "silver_schedule_resolved"
    __table_args__ = (
        UniqueConstraint("source_schedule_id", name="uq_silver_schedule_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("schedule.id", ondelete="CASCADE"), nullable=False
    )

    period: Mapped[str] = mapped_column(String(7), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    member_a_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    member_b_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    is_playoff: Mapped[bool] = mapped_column(Boolean, nullable=False)
    round_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    resolved_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<SilverScheduleResolved round={self.round_number} a={self.member_a_id} b={self.member_b_id}>"
