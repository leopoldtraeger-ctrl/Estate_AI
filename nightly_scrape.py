"""
Nightly scraper for EstateAI.

- Scrapes SALE & RENT listings from Rightmove
- Writes everything into estateai.db via ingest_bulk_results
- Designed to be run from GitHub Actions as well as locally.
"""

import os

from database.connection import get_session
from database.models import Base
from database.seed_benchmarks import seed_all_benchmarks
from database.ingest import ingest_bulk_results

# SALE: Haupt-Scraper
from scraper.sources.rightmove_scraper import scrape_all_sync
# RENT: eigener Rent-Scraper
from scraper.sources.rightmove_rent_scraper import scrape_all_rentals_sync


def ensure_db_initialized() -> None:
    """
    Create tables if they don't exist and seed benchmarks.
    """
    with get_session() as session:
        bind = session.get_bind()
        print(f"[DB] Using database URL: {bind.url}")
        Base.metadata.create_all(bind=bind)
        # idempotent: seed nur, wenn Tabellen leer sind
        seed_all_benchmarks(session)


def run_nightly_scrape() -> None:
    """
    Main entrypoint for the nightly job.

    Steuerbar über Env-Variablen (praktisch für GitHub Actions):

    - ESTATEAI_SCRAPE_LOCATION (default: "London")
    - ESTATEAI_SALE_PAGES     (default: "1")
    - ESTATEAI_RENT_PAGES     (default: "1")
    """

    location = os.getenv("ESTATEAI_SCRAPE_LOCATION", "London")
    sale_pages = int(os.getenv("ESTATEAI_SALE_PAGES", "1"))
    rent_pages = int(os.getenv("ESTATEAI_RENT_PAGES", "1"))

    print("========================================")
    print(" EstateAI Nightly Rightmove Scrape")
    print("========================================")
    print(f"Location:     {location}")
    print(f"SALE pages:   {sale_pages}")
    print(f"RENT pages:   {rent_pages}")
    print("========================================")

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

    print("✅ Nightly scrape finished.")


if __name__ == "__main__":
    run_nightly_scrape()
