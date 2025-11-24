"""
Connection & Session management for EstateAI database.
Uses SQLite for pitch/demo, but is Postgres-ready.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# For pitch/demo: local SQLite file.
# For Postgres later, change to e.g.:
# "postgresql+psycopg2://user:password@localhost:5432/estateai"
DATABASE_URL = "sqlite:///estateai.db"

# SQLAlchemy Base & Engine
Base = declarative_base()
engine = create_engine(
    DATABASE_URL,
    future=True,
    echo=False,  # auf True stellen, wenn du SQL sehen willst
)

# Session factory
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


def get_session():
    """
    Returns a new SQLAlchemy Session.
    Use with context manager:

        with get_session() as session:
            ...

    """
    return SessionLocal()


def init_db():
    """
    Initialize database: import models and create tables if missing.
    """
    # Import models so that they are registered on Base.metadata
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
