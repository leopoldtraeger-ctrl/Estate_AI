import pytest
import asyncio
from scraper.sources.rightmove_scraper import fetch_links, scrape_expose


@pytest.mark.asyncio
async def test_fetch_links():
    links = await fetch_links(max_pages=1)
    assert isinstance(links, list)
    assert len(links) > 0


@pytest.mark.asyncio
async def test_scrape_single():
    links = await fetch_links(max_pages=1)
    data = await scrape_expose(links[0])
    assert data.url.startswith("https://")
    assert data.source in ("dom", "ocr")
