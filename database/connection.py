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
    echo=False,          # auf True stellen, wenn du SQL sehen willst
    future=True,
    connect_args={"check_same_thread": False},  # wichtig für SQLite + mehrere Threads
)

# SessionFactory
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)


def init_db() -> None:
    """
    Tabellen anlegen, falls sie noch nicht existieren.
    Kannst du z.B. einmal beim Start aufrufen (lokal & im Workflow).
    """
    from . import models  # noqa: F401 – stellt sicher, dass alle Models registriert sind

    Base.metadata.create_all(bind=engine)


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


# Optional: automatische Initialisierung beim Import
# (kannst du lassen, weil es idempotent ist)
init_db()
