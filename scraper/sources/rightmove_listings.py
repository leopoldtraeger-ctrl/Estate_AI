import asyncio
import re
from playwright.async_api import async_playwright

BASE = "https://www.rightmove.co.uk"


# ----------------------------------------------------------
# Browser Setup
# ----------------------------------------------------------
async def launch_browser():
    pw = await async_playwright().start()

    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--disable-dev-shm-usage",
        ],
    )

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
async def safe_eval(page, selector):
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
# FETCH LISTINGS
# ----------------------------------------------------------
async def fetch_links(location="London", max_pages=1):
    pw, browser, page = await launch_browser()

    print(f"➡️ Fetching Rightmove listings for: {location}")

    # TODO: echte locationIdentifier-Mapping einbauen
    loc_id = "REGION^87490"  # London fallback

    links = []

    for p in range(max_pages):
        url = f"{BASE}/property-for-sale/find.html?locationIdentifier={loc_id}&index={p * 24}"

        print(f"📄 Loading listing page: {url}")
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

    # unique
    return list(set(links))


# ----------------------------------------------------------
# Helper: parse fields from full body text
# ----------------------------------------------------------
def parse_from_body_text(body_text: str):
    """
    Verwendet den reinen Text (ohne DOM-Selektoren),
    um price, property_type, bedrooms, bathrooms, description zu extrahieren.
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

    # --- BEDROOMS: Zeile nach "BEDROOMS" oder "4 bedrooms" etc. ---
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

    # --- BATHROOMS: analog ---
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

    # --- DESCRIPTION: alles nach "Description" bis zum nächsten Block ---
    in_desc = False
    desc_lines = []
    for l in lines:
        lower = l.lower()
        upper = l.upper()

        if not in_desc:
            if lower.startswith("description"):
                in_desc = True
            continue

        # Stop-Kandidaten: nächster Block-Header in ALL CAPS oder "HOLLAND PARK GATE DEVELOPMENT" etc.
        if upper == "-" or "DEVELOPMENT" in upper or upper.startswith("HOLLAND PARK GATE DEVELOPMENT"):
            break

        desc_lines.append(l)

    if desc_lines:
        description = "\n".join(desc_lines).strip()

    return price, property_type, bedrooms, bathrooms, description


# ----------------------------------------------------------
# SCRAPE ONE PROPERTY (v4.7)
# ----------------------------------------------------------
async def scrape_property(url):
    pw, browser, page = await launch_browser()

    print(f"🏠 Scraping: {url}")
    await page.goto(url, timeout=70000)
    await accept_cookies(page)

    # Warten, bis zumindest irgendwas Sinnvolles da ist
    try:
        await page.wait_for_selector("h1", timeout=15000)
    except Exception:
        pass

    await page.wait_for_timeout(1500)

    # Leicht scrollen, um Lazy Load zu triggern
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)
    except Exception:
        pass

    # --------------------- TITLE & ADDRESS -----------------------
    title = await safe_eval(page, "h1")

    # Manche Properties haben separate Address-Blöcke; best guess:
    address = await safe_eval(page, "[data-testid='address']") \
        or await safe_eval(page, "[data-testid='address-display']")

    # Wenn keine separate Address → nimm Title als Address
    if not address and title:
        address = title

    # --------------------- BODY-TEXT-PARSING --------------------
    try:
        body_text = await page.inner_text("body")
    except Exception:
        body_text = ""

    price, property_type, bedrooms, bathrooms, description = parse_from_body_text(body_text)

    # Fallback: description direkt aus DOM, falls vorhanden
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
async def scrape_all(location="London", pages=1):
    links = await fetch_links(location, pages)
    results = []

    print(f"📦 {len(links)} listings found.")

    for idx, url in enumerate(links):
        print(f"➡️ {idx + 1}/{len(links)} → {url}")
        try:
            data = await scrape_property(url)
            results.append(data)
        except Exception as e:
            print(f"❌ ERROR scraping {url}: {e}")

    return results


# ----------------------------------------------------------
# Sync wrappers (for FastAPI)
# ----------------------------------------------------------
def fetch_links_sync(location="London", pages=1):
    return asyncio.run(fetch_links(location, pages))


def scrape_property_sync(url: str):
    return asyncio.run(scrape_property(url))


def scrape_all_sync(location="London", pages=1):
    return asyncio.run(scrape_all(location, pages))
