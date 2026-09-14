"""
Database engine, session factory, and schema creation.

Every script in the pipeline talks to SQLite through this module so there is
exactly one place that decides where the file lives and how sessions are made.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# Importing the model modules registers their tables on Base.metadata -- needed
# before create_all(), and the reason this import block is not "unused".
import gold_models  # noqa: F401
import models  # noqa: F401
import silver_models  # noqa: F401
from models import Base

DEFAULT_DB_PATH = Path("data/fantasy_tracker.db")


def database_url(db_path: Path | str | None = None) -> str:
    """Resolve the SQLite URL, honouring DATABASE_URL if it is set."""
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def make_engine(db_path: Path | str | None = None) -> Engine:
    engine = create_engine(database_url(db_path), future=True)

    # SQLite does not enforce foreign keys unless asked, and the pragma is
    # per-connection -- so it has to be set on every connection as it is
    # created, not once on the pool. Without this, the ON DELETE CASCADE
    # behaviour the silver lineage depends on is silently unenforced.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create any missing tables. Safe to call on an existing database."""
    Base.metadata.create_all(engine)


def reset_db(engine: Engine) -> None:
    """
    Drop and recreate every table. Destructive -- used only by the roster
    seed's --force path, which is a full, deliberate rebuild.
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
