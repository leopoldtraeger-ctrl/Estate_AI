"""
Nightly Rightmove Scraper für GitHub Actions.

- Scraped N Seiten Rightmove (London)
- Schreibt alles in estateai.db
"""

from typing import Optional, Callable, List, Dict, Any

from scraper.sources.rightmove_scraper import scrape_all_sync
from database.ingest import ingest_bulk_results


Logger = Callable[[str], None]


def refresh_data(
    location: str = "London",
    pages: int = 5,
    logger: Optional[Logger] = None,
):
    """
    Läuft deinen Scraper + Ingest einmal durch,
    um neue Rightmove-Daten zu holen.
    """
    if logger is None:
        logger = print

    logger(f"🚀 Starting nightly scrape for location={location}, pages={pages}")

    # Scrapen
    results: List[Dict[str, Any]] = scrape_all_sync(
        location=location,
        pages=pages,
        logger=logger,
    )

    logger(f"💾 Ingesting {len(results)} scraped listings into estateai.db …")

    # Ingest in DB
    total, success, error = ingest_bulk_results(
        results,
        portal="rightmove",
        location_query=f"{location}, pages={pages}",
        listing_type="sale",
    )

    logger(f"✅ Done. total={total}, success={success}, error={error}")
    return total, success, error


if __name__ == "__main__":
    # HIER kannst du später einfach die Seitenzahl hochdrehen:
    PAGES_TO_SCRAPE = 5

    def console_logger(msg: str):
        print(msg)

    refresh_data(location="London", pages=PAGES_TO_SCRAPE, logger=console_logger)

