import asyncio
from scraper.sources.rightmove_scraper import fetch_links, scrape_expose
from database.ingest import save_listing

async def run():
    print("Fetching links…")
    links = await fetch_links(max_pages=1)

    print(f"Found {len(links)} links")

    if not links:
        print("❌ No links found")
        return

    url = links[0]
    print(f"Scraping first: {url}")

    data = await scrape_expose(url)

    print("\nExtracted:")
    print(data)

    save_listing(data)
    print("\n💾 Saved to database!")

if __name__ == "__main__":
    asyncio.run(run())
