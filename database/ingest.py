"""
High-level Ingest-Layer für den Scraper.

Ziel: Deine Scraper-Funktion gibt eine Liste von dicts zurück;
hier werden sie mit einem ScrapeRun in die DB geschrieben.
"""

from typing import Any, Dict, Iterable, Optional, Tuple

from sqlalchemy.orm import Session

from .connection import get_session, init_db
from . import crud, models


def _ensure_run(
    session: Session,
    portal: str,
    location_query: Optional[str],
    run: Optional[models.ScrapeRun],
) -> models.ScrapeRun:
    if run is not None:
        return run
    return crud.create_scrape_run(session, portal=portal, location_query=location_query)


def ingest_single_result(
    scraped: Dict[str, Any],
    raw_text: Optional[str] = None,
    raw_meta: Optional[str] = None,
    portal: str = "rightmove",
    location_query: Optional[str] = None,
    listing_type: str = "sale",
    run: Optional[models.ScrapeRun] = None,
) -> Tuple[int, int, int]:
    """
    Ingest nur eines einzelnen Scraper-Resultats (z.B. für Tests oder API-Call).
    Gibt (total, success, error) zurück.
    """
    init_db()  # stellt sicher, dass Tabellen existieren

    total = 1
    success = 0
    error = 0

    with get_session() as session:
        try:
            run_obj = _ensure_run(session, portal, location_query, run)
            crud.upsert_listing_from_scrape(
                session=session,
                scraped=scraped,
                run=run_obj,
                portal=portal,
                listing_type=listing_type,
                raw_text=raw_text,
                raw_meta=raw_meta,
            )
            success += 1
            crud.finish_scrape_run(
                session=session,
                run=run_obj,
                total_listings=total,
                success_count=success,
                error_count=error,
                status="success" if error == 0 else "partial",
            )
            session.commit()
        except Exception:
            session.rollback()
            error += 1
            raise

    return total, success, error


def ingest_bulk_results(
    results: Iterable[Dict[str, Any]],
    portal: str = "rightmove",
    location_query: Optional[str] = None,
    listing_type: str = "sale",
) -> Tuple[int, int, int]:
    """
    Ingest für mehrere Scraper-Resultate auf einmal.

    results: Iterable von dicts wie aus deinem Rightmove-Scraper.
    """
    init_db()

    total = 0
    success = 0
    error = 0

    with get_session() as session:
        run_obj = crud.create_scrape_run(
            session=session,
            portal=portal,
            location_query=location_query,
        )

        for scraped in results:
            total += 1
            try:
                crud.upsert_listing_from_scrape(
                    session=session,
                    scraped=scraped,
                    run=run_obj,
                    portal=portal,
                    listing_type=listing_type,
                )
                success += 1
            except Exception:
                error += 1
                # Fehler einzelner Listings loggen / später erweitern
                session.rollback()
                # Danach weiterlaufen, aber Run nicht abbrechen
                with session.begin():
                    pass

        crud.finish_scrape_run(
            session=session,
            run=run_obj,
            total_listings=total,
            success_count=success,
            error_count=error,
            status="success" if error == 0 else "partial",
        )
        session.commit()

    return total, success, error
