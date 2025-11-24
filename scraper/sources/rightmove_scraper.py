# scraper/sources/rightmove_scraper.py

import asyncio
import re
import sys
import subprocess
from typing import List, Dict, Any, Optional, Callable

from playwright.async_api import async_playwright

BASE = "https://www.rightmove.co.uk"

Logger = Callable[[str], None]


def _log(logger: Optional[Logger], msg: str):
    """Kleiner Helper: wenn kein logger übergeben wird -> print."""
    if logger is not None:
        logger(msg)
    else:
        print(msg)


# ----------------------------------------------------------
# Playwright-Browser (Chromium) sicher installieren
# ----------------------------------------------------------
def ensure_browsers_installed(logger: Optional[Logger] = None):
    """
    Wird auf Streamlit Cloud gebraucht: dort ist zwar das Playwright-Python-
    Paket installiert, aber NICHT automatisch der Chromium-Browser.

    Läuft nur, falls der Launch zuvor mit "Executable doesn't exist" scheitert.
    """
    _log(
        logger,
        "Looks like the Playwright browser is missing. "
        "Installing Chromium browser (this can take 30–60 seconds on first run)…",
    )

    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    try:
        subprocess.run(cmd, check=True)
        _log(logger, "Playwright Chromium installation finished ✅")
    except Exception as e:
        _log(logger, f"❌ Failed to install Playwright browsers automatically: {e}")
        # Fehler weiterwerfen, damit du es im Log siehst
        raise


# ----------------------------------------------------------
# Browser Setup
# ----------------------------------------------------------
async def launch_browser(logger: Optional[Logger] = None):
    pw = await async_playwright().start()

    try:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-dev-shm-usage",
            ],
        )
    except Exception as e:
        # Typischer Streamlit-Cloud-Fehler: Executable doesn't exist …
        if "Executable doesn't exist" in str(e):
            await pw.stop()
            # Browser-Binaries nachinstallieren
            ensure_browsers_installed(logger)

            # Noch einmal versuchen
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-dev-shm-usage",
                ],
            )
        else:
            await pw.stop()
            raise

    context = await browser.new_context(
        viewport={"width": 1600, "height": 1200},
        locale="en-GB",
        java_script_enabled=True,
        bypass_csp=True,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
    )

    # Basic anti-bot hardening
    await context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });

        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );
        """
    )

    page = await context.new_page()
    return pw, browser, page


# ----------------------------------------------------------
# Accept Cookies
# ----------------------------------------------------------
async def accept_cookies(page):
    try:
        await page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
    except Exception:
        pass

    try:
        await page.locator("button[aria-label='Accept all']").click(timeout=3000)
    except Exception:
        pass


# ----------------------------------------------------------
# Safe innerText evaluator
# ----------------------------------------------------------
async def safe_eval(page, selector: str):
    try:
        el = await page.query_selector(selector)
        if el:
            txt = await el.inner_text()
            if txt:
                return txt.strip()
    except Exception:
        return None
    return None


# ----------------------------------------------------------
# Helper: parse property fields from full body text
# ----------------------------------------------------------
def parse_from_body_text(body_text: str):
    """
    Verwendet den reinen Body-Text, um price, property_type,
    bedrooms, bathrooms und description robust herauszuziehen.
    """
    lines = [l.strip() for l in body_text.splitlines() if l.strip()]

    price = None
    property_type = None
    bedrooms = None
    bathrooms = None
    description = ""

    # --- PRICE: erste Zeile, die mit £ beginnt ---
    for l in lines:
        if l.startswith("£"):
            m = re.search(r"£\s*[\d,]+", l)
            if m:
                price = m.group(0)
                break

    # --- PROPERTY TYPE: Zeile nach "PROPERTY TYPE" ---
    for idx, l in enumerate(lines):
        if l.upper() == "PROPERTY TYPE" and idx + 1 < len(lines):
            property_type = lines[idx + 1]
            break

    # --- BEDROOMS: nach "BEDROOMS" oder "10 bedrooms" etc. ---
    if not bedrooms:
        for idx, l in enumerate(lines):
            if l.upper() == "BEDROOMS" and idx + 1 < len(lines):
                m = re.search(r"\d+", lines[idx + 1])
                if m:
                    bedrooms = m.group(0)
                    break
    if not bedrooms:
        for l in lines:
            m = re.search(r"(\d+)\s*bedrooms?", l, re.I)
            if m:
                bedrooms = m.group(1)
                break

    # --- BATHROOMS ---
    if not bathrooms:
        for idx, l in enumerate(lines):
            if l.upper() == "BATHROOMS" and idx + 1 < len(lines):
                m = re.search(r"\d+", lines[idx + 1])
                if m:
                    bathrooms = m.group(0)
                    break
    if not bathrooms:
        for l in lines:
            m = re.search(r"(\d+)\s*bathrooms?", l, re.I)
            if m:
                bathrooms = m.group(1)
                break

    # --- DESCRIPTION: alles nach "Description" bis zum nächsten Block/Meta ---
    in_desc = False
    desc_lines = []
    for l in lines:
        lower = l.lower()
        upper = l.upper()

        if not in_desc:
            if lower.startswith("description"):
                in_desc = True
            continue

        # Stop-Kandidaten: Meta-Blöcke, Agent-Info etc.
        stop_markers = [
            "COUNCIL TAX",
            "Energy performance certificate",
            "Utilities, rights & restrictions",
            "CHECK HOW MUCH YOU CAN BORROW",
            "ABOUT UNITED KINGDOM SOTHEBY'S INTERNATIONAL REALTY",
        ]
        if any(sm in upper for sm in stop_markers):
            break

        desc_lines.append(l)

    if desc_lines:
        description = "\n".join(desc_lines).strip()

    return price, property_type, bedrooms, bathrooms, description


# ----------------------------------------------------------
# FETCH LISTINGS
# ----------------------------------------------------------
async def fetch_links(
    location: str = "London",
    max_pages: int = 1,
    logger: Optional[Logger] = None,
) -> List[str]:
    """
    Holt Listings für eine Region. Aktuell: locationIdentifier hardcoded für London.
    Später können wir ein Mapping für andere Regionen ergänzen.
    """
    if logger is None:
        logger = print  # Fallback

    pw, browser, page = await launch_browser(logger=logger)

    logger(f"➡️ Fetching Rightmove listings for: {location}")

    # TODO: echtes Mapping bauen; für Pitch reicht London:
    loc_id = "REGION^87490"  # London

    links: List[str] = []

    for p in range(max_pages):
        url = f"{BASE}/property-for-sale/find.html?locationIdentifier={loc_id}&index={p * 24}"

        logger(f"📄 Loading listing page: {url}")
        await page.goto(url, timeout=70000)
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
    return list(set(links))


# ----------------------------------------------------------
# SCRAPE ONE PROPERTY
# ----------------------------------------------------------
async def scrape_property(url: str, logger: Optional[Logger] = None) -> Dict[str, Any]:
    if logger is None:
        logger = print

    pw, browser, page = await launch_browser(logger=logger)

    logger(f"🏠 Scraping: {url}")
    await page.goto(url, timeout=70000)
    await accept_cookies(page)

    # Warten, bis zumindest der Title da ist
    try:
        await page.wait_for_selector("h1", timeout=15000)
    except Exception:
        pass

    await page.wait_for_timeout(1500)

    # Scrollen, um Lazy Load zu triggern
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)
    except Exception:
        pass

    # TITLE & ADDRESS
    title = await safe_eval(page, "h1")
    address = await safe_eval(page, "[data-testid='address']") \
        or await safe_eval(page, "[data-testid='address-display']")

    if not address and title:
        address = title

    # BODY TEXT
    try:
        body_text = await page.inner_text("body")
    except Exception:
        body_text = ""

    price, property_type, bedrooms, bathrooms, description = parse_from_body_text(body_text)

    # Fallback Description direkt aus DOM
    if not description:
        description = await safe_eval(page, "[data-testid='description']") \
            or await safe_eval(page, "[data-testid='read-full-description']") \
            or ""

    await browser.close()
    await pw.stop()

    return {
        "url": url,
        "title": title,
        "price": price,
        "address": address,
        "description": description,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "property_type": property_type,
        "source": "v4.7_textparse",
    }


# ----------------------------------------------------------
# Complete Workflow: Listings → Property Details
# ----------------------------------------------------------
async def scrape_all(
    location: str = "London",
    pages: int = 1,
    logger: Optional[Logger] = None,
) -> List[Dict[str, Any]]:
    if logger is None:
        logger = print

    links = await fetch_links(location, pages, logger=logger)
    logger(f"📦 {len(links)} listings found.")

    results: List[Dict[str, Any]] = []

    for idx, url in enumerate(links):
        logger(f"➡️ {idx + 1}/{len(links)} → {url}")
        try:
            data = await scrape_property(url, logger=logger)
            results.append(data)
        except Exception as e:
            logger(f"❌ ERROR scraping {url}: {e}")

    return results


# ----------------------------------------------------------
# Sync wrapper (für Pipelines & FastAPI)
# ----------------------------------------------------------
def scrape_all_sync(
    location: str = "London",
    pages: int = 1,
    logger: Optional[Logger] = None,
) -> List[Dict[str, Any]]:
    return asyncio.run(scrape_all(location, pages, logger=logger))
