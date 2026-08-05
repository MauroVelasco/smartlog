"""
SQLAlchemy engine/session management for the Relationship Store
(architecture slide 5, stage 4: "Normalized events + inferred links —
Postgres / graph").
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import config

_engine: Engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)

# Secondary engines for DB log extraction (extraction/db_log_extractor.py),
# keyed by connection_name from DB_LOG_SOURCES, e.g. "oracle:app" ->
# looks up DATABASE_URL_APP in the environment.
_secondary_engines: Dict[str, Engine] = {}


def get_engine() -> Engine:
    return _engine


def get_engine_for(connection_name: str) -> Engine:
    import os

    if connection_name not in _secondary_engines:
        env_key = f"DATABASE_URL_{connection_name.upper()}"
        url = os.getenv(env_key)
        if not url:
            raise RuntimeError(f"No connection string configured for '{connection_name}' (expected {env_key})")
        _secondary_engines[connection_name] = create_engine(url, pool_pre_ping=True, future=True)
    return _secondary_engines[connection_name]


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
