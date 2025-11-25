# nightly_scrape.py
"""
Nightly Job für GitHub Actions / Cron:
- Rightmove SALE scrapen
- Rightmove RENT scrapen
- Alle Daten in estateai.db schreiben
- Mietspiegel (rent_benchmarks) neu berechnen
"""

from database.connection import get_session
from database.models import Base
from database.ingest import ingest_bulk_results

from scraper.sources.rightmove_scraper import scrape_all_sync
from scraper.sources.rightmove_rent_scraper import scrape_all_rentals_sync

from pipelines.build_rent_benchmarks import build_rent_benchmarks


def ensure_db_initialized() -> None:
    """
    Stellt sicher, dass alle Tabellen existieren.
    (Falls du noch seed_benchmarks benutzt, kannst du das hier auch reinziehen.)
    """
    with get_session() as s:
        bind = s.get_bind()
        Base.metadata.create_all(bind=bind)


def run_nightly(location: str = "London", pages: int = 5) -> None:
    ensure_db_initialized()

    # 1) SALE – Kaufangebote
    print("=== Scraping SALE listings ===")
    sale_results = scrape_all_sync(location=location, pages=pages)
    print(f"Scraped SALE listings: {len(sale_results)}")

    ingest_sale = ingest_bulk_results(
        sale_results,
        portal="rightmove",
        location_query=f"{location} (sale), pages={pages}",
        listing_type="sale",
    )
    print("Ingest SALE result:", ingest_sale)

    # 2) RENT – Mietangebote
    print("=== Scraping RENT listings ===")
    rent_results = scrape_all_rentals_sync(location=location, pages=pages)
    print(f"Scraped RENT listings: {len(rent_results)}")

    ingest_rent = ingest_bulk_results(
        rent_results,
        portal="rightmove",
        location_query=f"{location} (rent), pages={pages}",
        listing_type="rent",
    )
    print("Ingest RENT result:", ingest_rent)

    # 3) Mietspiegel / Benchmarks
    print("=== Building rent benchmarks ===")
    created = build_rent_benchmarks()
    print(f"Rent benchmark buckets created: {created}")


if __name__ == "__main__":
    # Default: London, 5 Seiten – genau wie dein bisheriger Job
    run_nightly(location="London", pages=5)
