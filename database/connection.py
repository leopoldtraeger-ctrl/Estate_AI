from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

# SQLite-DB im Projektroot:
DB_PATH = Path(__file__).resolve().parents[1] / "estateai.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Engine bauen
engine = create_engine(
    DATABASE_URL,
    echo=False,        # auf True stellen, wenn du SQL sehen willst
    future=True,
)

# Tabellen automatisch anlegen (idempotent)
Base.metadata.create_all(bind=engine)

# SessionFactory
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)


@contextmanager
def get_session():
    """
    Contextmanager für DB-Session:
    with get_session() as session:
        ...
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
