"""
Database package for EstateAI.

Usage example:

    from database import init_db, get_session
    from database import crud, models

    init_db()
    with get_session() as session:
        ...

"""

from .connection import init_db, get_session, Base, engine
from . import models, crud  # noqa: F401
