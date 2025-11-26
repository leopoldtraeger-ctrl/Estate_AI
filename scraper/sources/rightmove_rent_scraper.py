# scraper/sources/rightmove_rent_scraper.py

import asyncio
from typing import List, Dict, Any, Optional, Callable

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .rightmove_scraper import (
    BASE,
    launch_browser,
    accept_cookies,
    safe_eval,
    parse_from_body_text,
    Logger,
    _log,
)


# ----------------------------------------------------------
# FETCH RENTAL LISTINGS (to rent)
# ----------------------------------------------------------
async def fetch_rent_links(
    location: str = "London",
    max_pages: int = 1,
    logger: Optional[Logger] = None,
) -> List[str]:
    """
    Holt Miet-Listings (to rent) für eine Region.
    Aktuell: locationIdentifier hardcoded für London (REGION^87490).
    """
    if logger is None:
        logger = print

    pw, browser, page = await launch_browser(logger=logger)

    logger(f"➡️ Fetching Rightmove *rental* listings for: {location}")

    # TODO: echtes Mapping bauen; aktuell London-Fallback
    loc_id = "REGION^87490"  # London

    links: List[str] = []

    for p in range(max_pages):
        # WICHTIG: property-to-rent statt property-for-sale
        url = f"{BASE}/property-to-rent/find.html?locationIdentifier={loc_id}&index={p * 24}"

        logger(f"📄 Loading RENT listing page: {url}")
        try:
            await page.goto(url, timeout=70000, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as e:
            logger(f"❌ Timeout loading rent listing page {url}: {e}")
            continue

        await accept_cookies(page)
        await page.wait_for_timeout(2000)

        cards = await page.query_selector_all("a.propertyCard-link")

        for c in cards:
            href = await c.get_attribute("href")
            if href and "/properties/" in href:
                clean = BASE + href.split("?")[0]
                links.append(clean)

    await browser.close()
    await pw.stop()

    # dedupe
    return list(dict.fromkeys(links))


# ----------------------------------------------------------
# SCRAPE ONE RENTAL PROPERTY
# ----------------------------------------------------------
async def scrape_rent_property(
    url: str,
    logger: Optional[Logger] = None,
) -> Dict[str, Any]:
    """
    Liest eine Miet-Immobilie aus.
    Nutzt denselben Body-Text-Parser wie der Kauf-Scraper.
    'price' ist hier die Miete (meist £/pcm).
    """
    if logger is None:
        logger = print

    pw, browser, page = await launch_browser(logger=logger)

    logger(f"🏠 [RENT] Scraping: {url}")
    try:
        await page.goto(url, timeout=70000, wait_until="domcontentloaded")
    except PlaywrightTimeoutError as e:
        logger(f"❌ Timeout loading rent property page {url}: {e}")
        await browser.close()
        await pw.stop()
        return {
            "url": url,
            "title": None,
            "price": None,
            "address": None,
            "description": None,
            "bedrooms": None,
            "bathrooms": None,
            "property_type": None,
            "floor_area_sqm": None,
            "year_built": None,
            "energy_rating": None,
            "refurb_intensity": None,
            "source": "rent_v1_timeout",
            "error": f"timeout: {e}",
        }

    await accept_cookies(page)

    try:
        await page.wait_for_selector("h1", timeout=15000)
    except Exception:
        pass

    await page.wait_for_timeout(1500)

    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)
    except Exception:
        pass

    # Titel & Adresse
    title = await safe_eval(page, "h1")
    address = await safe_eval(page, "[data-testid='address']") \
        or await safe_eval(page, "[data-testid='address-display']")

    if not address and title:
        address = title

    # Volltext
    try:
        body_text = await page.inner_text("body")
    except Exception:
        body_text = ""

    (
        price,
        property_type,
        bedrooms,
        bathrooms,
        description,
        floor_area_sqm,
        year_built,
        energy_rating,
        refurb_intensity,
    ) = parse_from_body_text(body_text)

    # Fallback Description
    if not description:
        description = await safe_eval(page, "[data-testid='description']") \
            or await safe_eval(page, "[data-testid='read-full-description']") \
            or ""

    await browser.close()
    await pw.stop()

    return {
        "url": url,
        "title": title,
        # price = Miete (meist PCM), Key bleibt 'price' für ingest_bulk_results
        "price": price,
        "address": address,
        "description": description,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "property_type": property_type,
        "floor_area_sqm": floor_area_sqm,
        "year_built": year_built,
        "energy_rating": energy_rating,
        "refurb_intensity": refurb_intensity,
        "source": "rent_v1_textparse_construction",
    }


# ----------------------------------------------------------
# COMPLETE RENTAL WORKFLOW
# ----------------------------------------------------------
async def scrape_all_rentals(
    location: str = "London",
    pages: int = 1,
    logger: Optional[Logger] = None,
) -> List[Dict[str, Any]]:
    if logger is None:
        logger = print

    links = await fetch_rent_links(location, pages, logger=logger)
    logger(f"📦 [RENT] {len(links)} rental listings found.")

    results: List[Dict[str, Any]] = []

    for idx, url in enumerate(links):
        logger(f"➡️ [RENT] {idx + 1}/{len(links)} → {url}")
        try:
            data = await scrape_rent_property(url, logger=logger)
            results.append(data)
        except Exception as e:
            logger(f"❌ ERROR scraping rent property {url}: {e}")

    return results


# ----------------------------------------------------------
# Sync Wrapper (für Pipelines & FastAPI)
# ----------------------------------------------------------
def fetch_rent_links_sync(
    location: str = "London",
    pages: int = 1,
    logger: Optional[Logger] = None,
) -> List[str]:
    return asyncio.run(fetch_rent_links(location, pages, logger=logger))


def scrape_rent_property_sync(
    url: str,
    logger: Optional[Logger] = None,
) -> Dict[str, Any]:
    return asyncio.run(scrape_rent_property(url, logger=logger))


def scrape_all_rentals_sync(
    location: str = "London",
    pages: int = 1,
    logger: Optional[Logger] = None,
) -> List[Dict[str, Any]]:
    return asyncio.run(scrape_all_rentals(location, pages, logger=logger))
