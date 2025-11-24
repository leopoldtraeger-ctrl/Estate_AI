# pipelines/rightmove_scrape_and_ingest.py

from database.ingest import ingest_bulk_results
from scraper.sources.rightmove_scraper import scrape_all_sync


def main():
    print("🚀 Starting Rightmove scrape + ingest pipeline...")

    location = "London"
    pages = 1

    print(f"📡 Scraping Rightmove for location={location}, pages={pages} ...")
    results = scrape_all_sync(location=location, pages=pages)
    print(f"✅ Scraper returned {len(results)} results.")

    if not results:
        print("⚠️ No results returned – check scraper or selectors.")
        return

    print("💾 Ingesting results into database...")
    total, success, error = ingest_bulk_results(
        results,
        portal="rightmove",
        location_query=f"{location}, pages={pages}",
        listing_type="sale",
    )

    print(f"🎉 Ingest finished: total={total}, success={success}, error={error}")


if __name__ == "__main__":
    main()
