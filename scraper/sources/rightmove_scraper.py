# scraper/sources/rightmove_scraper.py

import asyncio
import re
import sys
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://www.rightmove.co.uk"

Logger = Callable[[str], None]


def _log(logger: Optional[Logger], msg: str) -> None:
    """Helper: wenn kein logger übergeben wird -> print()."""
    if logger is not None:
        logger(msg)
    else:
        print(msg)


# ----------------------------------------------------------
# Playwright-Browser (Chromium) sicher installieren
# ----------------------------------------------------------
def ensure_browsers_installed(logger: Optional[Logger] = None) -> None:
    """
    Für Umgebungen wie Streamlit Cloud / GitHub Actions:
    - Python-Paket 'playwright' ist installiert
    - aber der Chromium-Browser nicht
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
        # Typischer Fehler in Cloud-Umgebungen:
        # "Executable doesn't exist at /home/.../ms-playwright/chromium-..."
        if "Executable doesn't exist" in str(e):
            await pw.stop()
            ensure_browsers_installed(logger)

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
async def accept_cookies(page) -> None:
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
async def safe_eval(page, selector: str) -> Optional[str]:
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
# Construction-Helper (Wohnfläche, Baujahr, EPC, Zustand)
# ----------------------------------------------------------

AREA_PATTERNS = [
    r"(?P<value>\d[\d,\.]*)\s*(sq\.?\s*ft|sqft|sq ft)",
    r"(?P<value>\d[\d,\.]*)\s*(sq\.?\s*m|sqm|sq m)",
]

YEAR_PATTERNS = [
    r"built in\s+(?P<year>19\d{2}|20\d{2})",
    r"built circa\s+(?P<year>19\d{2}|20\d{2})",
    r"circa\s+(?P<year>19\d{2}|20\d{2})",
]


def _clean_number(num_str: str) -> Optional[float]:
    try:
        num_str = num_str.replace(",", "").strip()
        return float(num_str)
    except Exception:
        return None


def extract_floor_area_sqm(text: str) -> Optional[float]:
    """
    Sucht nach '850 sq ft' oder '79 sq m' im Text und liefert m².
    """
    if not text:
        return None

    t = text.lower()
    for pattern in AREA_PATTERNS:
        m = re.search(pattern, t)
        if not m:
            continue
        val = _clean_number(m.group("value"))
        if val is None:
            continue

        unit = m.group(0).lower()
        if "ft" in unit:
            # sq ft -> m²
            return val * 0.092903
        else:
            # bereits m²
            return val

    return None


def extract_year_built(text: str) -> Optional[int]:
    """
    Sucht 'built in 1930', 'built circa 1900' usw.
    """
    if not text:
        return None

    t = text.lower()
    for pattern in YEAR_PATTERNS:
        m = re.search(pattern, t)
        if m:
            try:
                year = int(m.group("year"))
                if 1800 <= year <= datetime.now().year:
                    return year
            except Exception:
                continue
    return None


def extract_energy_rating(text: str) -> Optional[str]:
    """
    Sucht nach 'EPC C', 'EPC rating D', 'Energy performance ... B' etc.
    """
    if not text:
        return None

    t = text.lower()
    m = re.search(r"epc[^a-g]*([a-g])", t)
    if m:
        rating = m.group(1).upper()
        if rating in list("ABCDEFG"):
            return rating
    return None


def infer_refurb_intensity(text: str) -> str:
    """
    Sehr einfache Heuristik für Refurb-Intensity basierend auf Beschreibung.
    """
    if not text:
        return "none"

    t = text.lower()

    # Full Refurb nötig
    full_keywords = [
        "requires complete refurbishment",
        "in need of complete refurbishment",
        "in need of modernisation",
        "requires modernisation",
        "full refurbishment",
        "total renovation",
    ]
    if any(k in t for k in full_keywords):
        return "full"

    # Medium
    medium_keywords = [
        "scope for improvement",
        "some updating required",
        "tired condition",
        "outdated",
        "dated interior",
    ]
    if any(k in t for k in medium_keywords):
        return "medium"

    # Light / schon gemacht
    light_keywords = [
        "recently refurbished",
        "newly refurbished",
        "newly renovated",
        "recently renovated",
        "brand new kitchen",
        "new bathroom",
    ]
    if any(k in t for k in light_keywords):
        return "light"

    return "none"


# ----------------------------------------------------------
# Helper: parse property fields from full body text
# ----------------------------------------------------------
def parse_from_body_text(body_text: str):
    """
    Verwendet den reinen Body-Text, um price, property_type,
    bedrooms, bathrooms, description + floor_area_sqm, year_built,
    energy_rating und refurb_intensity herauszuziehen.
    """
    lines = [l.strip() for l in body_text.splitlines() if l.strip()]

    price = None
    property_type = None
    bedrooms = None
    bathrooms = None
    description = ""

    floor_area_sqm = None
    year_built = None
    energy_rating = None
    refurb_intensity = "none"

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

        stop_markers = [
            "COUNCIL TAX",
            "ENERGY PERFORMANCE CERTIFICATE",
            "UTILITIES, RIGHTS & RESTRICTIONS",
            "CHECK HOW MUCH YOU CAN BORROW",
            "ABOUT ",
        ]
        if any(sm in upper for sm in stop_markers):
            break

        desc_lines.append(l)

    if desc_lines:
        description = "\n".join(desc_lines).strip()

    # ====================================================
    # 🆕 Floor area (sq ft / sq m)
    # ====================================================
    def _parse_number(s: str) -> float | None:
        s_clean = re.sub(r"[^\d\.]", "", s)
        if not s_clean:
            return None
        try:
            return float(s_clean)
        except Exception:
            return None

    # zuerst nach m² suchen
    m2_match = re.search(
        r"([\d,\.]+)\s*(?:sq\.?\s*m|sqm|square metres?|square meters?)",
        body_text,
        flags=re.I,
    )
    if m2_match:
        val = _parse_number(m2_match.group(1))
        if val:
            floor_area_sqm = val
    else:
        # dann sq ft → in m² umrechnen
        ft_match = re.search(
            r"([\d,\.]+)\s*(?:sq\.?\s*ft|sqft|square feet)",
            body_text,
            flags=re.I,
        )
        if ft_match:
            val = _parse_number(ft_match.group(1))
            if val:
                floor_area_sqm = val * 0.092903

    # ====================================================
    # 🆕 Year built
    # ====================================================
    year_match = re.search(
        r"(?:built|constructed|erected|completed)\s+(?:in\s+)?(19\d{2}|20\d{2})",
        body_text,
        flags=re.I,
    )
    if not year_match:
        year_match = re.search(
            r"circa\s+(19\d{2}|20\d{2})",
            body_text,
            flags=re.I,
        )
    if year_match:
        try:
            year_built = int(year_match.group(1))
        except Exception:
            year_built = None

    # ====================================================
    # 🆕 Energy / EPC rating
    # ====================================================
    epc_match = re.search(
        r"(?:EPC|Energy (?:Performance )?Rating|Energy rating)\s*[:\-]?\s*([A-G][\+\-]?)",
        body_text,
        flags=re.I,
    )
    if epc_match:
        energy_rating = epc_match.group(1).upper()

    # ====================================================
    # 🆕 Refurb intensity heuristic (aus Beschreibung)
    # ====================================================
    text = (description or body_text).lower()

    full_terms = [
        "in need of modernisation",
        "in need of modernization",
        "requires modernisation",
        "requires modernization",
        "complete refurbishment",
        "full refurbishment",
        "total refurbishment",
        "unmodernised",
        "unmodernized",
        "shell condition",
    ]
    medium_terms = [
        "requires some updating",
        "scope to improve",
        "scope for improvement",
        "dated condition",
        "requires updating",
        "needs updating",
    ]
    light_terms = [
        "newly refurbished",
        "recently refurbished",
        "newly renovated",
        "recently renovated",
        "immaculate condition",
        "turn-key",
        "turnkey",
        "ready to move in",
    ]

    if any(t in text for t in full_terms):
        refurb_intensity = "full"
    elif any(t in text for t in medium_terms):
        refurb_intensity = "medium"
    elif any(t in text for t in light_terms):
        refurb_intensity = "light"
    else:
        refurb_intensity = "none"

    return (
        price,
        property_type,
        bedrooms,
        bathrooms,
        description,
        floor_area_sqm,
        year_built,
        energy_rating,
        refurb_intensity,
    )



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

    loc_id = "REGION^87490"  # London

    links: List[str] = []

    for p in range(max_pages):
        url = f"{BASE}/property-for-sale/find.html?locationIdentifier={loc_id}&index={p * 24}"

        logger(f"📄 Loading listing page: {url}")
        try:
            # etwas „leichteres“ wait_until + Timeout abfangen
            await page.goto(url, timeout=70000, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as e:
            logger(f"❌ Timeout loading listing page {url}: {e}")
            # nächste Seite probieren, aber NICHT den ganzen Run crashen
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
    return list(set(links))


# ----------------------------------------------------------
# SCRAPE ONE PROPERTY
# ----------------------------------------------------------
async def scrape_property(url: str, logger: Optional[Logger] = None) -> Dict[str, Any]:
    if logger is None:
        logger = print

    pw, browser, page = await launch_browser(logger=logger)

    logger(f"🏠 Scraping: {url}")
    try:
        await page.goto(url, timeout=70000, wait_until="domcontentloaded")
    except PlaywrightTimeoutError as e:
        logger(f"❌ Timeout loading property page {url}: {e}")
        await browser.close()
        await pw.stop()
        # Fehler-Record zurückgeben, damit der Run weiterläuft
        return {
            "url": url,
            "title": None,
            "price": None,
            "address": None,
            "description": None,
            "bedrooms": None,
            "bathrooms": None,
            "property_type": None,
            "source": "v4.8_textparse_timeout",
            "error": f"timeout: {e}",
        }

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


    # Fallback Description direkt aus DOM
    if not description:
        description = await safe_eval(page, "[data-testid='description']") \
            or await safe_eval(page, "[data-testid='read-full-description']") \
            or ""

    # ---------- NEU: Construction-Felder aus Text ----------
    combined_text = f"{description}\n\n{body_text}"
    floor_area_sqm = extract_floor_area_sqm(combined_text)
    year_built = extract_year_built(combined_text)
    energy_rating = extract_energy_rating(combined_text)
    refurb_intensity = infer_refurb_intensity(combined_text)

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
        "floor_area_sqm": floor_area_sqm,
        "year_built": year_built,
        "energy_rating": energy_rating,
        "refurb_intensity": refurb_intensity,
        "source": "v4.8_textparse_construction",
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
