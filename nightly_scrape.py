# scripts/nightly_scrape.py

"""
Nightly scraper for EstateAI.

- Scrapes SALE & RENT listings from Rightmove
- Writes everything into estateai.db via ingest_bulk_results
"""

from database.connection import get_session
from database.models import Base
from database.seed_benchmarks import seed_all_benchmarks
from database.ingest import ingest_bulk_results
from scraper.sources.rightmove_scraper import (
    scrape_all_sync,
    scrape_all_rentals_sync,
)


def ensure_db_initialized() -> None:
    """
    Create tables if they don't exist and seed benchmarks.
    """
    with get_session() as session:
        bind = session.get_bind()
        Base.metadata.create_all(bind=bind)
        # idempotent: nur wenn leer
        seed_all_benchmarks(session)


def run_nightly_scrape(
    location: str = "London",
    sale_pages: int = 20,
    rent_pages: int = 20,
) -> None:
    """
    Main entrypoint for the nightly job.
    Increase sale_pages / rent_pages wenn du mehr Daten willst.
    """
    ensure_db_initialized()

    # -------- SALE --------
    print(f"▶ Scraping SALE listings for {location}, pages={sale_pages}")
    sale_results = scrape_all_sync(location=location, pages=sale_pages)
    print(f"SALE scraped: {len(sale_results)} rows")

    total_s, success_s, error_s = ingest_bulk_results(
        sale_results,
        portal="rightmove",
        location_query=f"{location}, pages={sale_pages}",
        listing_type="sale",
    )
    print(f"SALE ingest result: total={total_s}, success={success_s}, error={error_s}")

    # -------- RENT --------
    print(f"▶ Scraping RENT listings for {location}, pages={rent_pages}")
    rent_results = scrape_all_rentals_sync(location=location, pages=rent_pages)
    print(f"RENT scraped: {len(rent_results)} rows")

    total_r, success_r, error_r = ingest_bulk_results(
        rent_results,
        portal="rightmove",
        location_query=f"{location}, pages={rent_pages}",
        listing_type="rent",
    )
    print(f"RENT ingest result: total={total_r}, success={success_r}, error={error_r}")


if __name__ == "__main__":
    run_nightly_scrape()
