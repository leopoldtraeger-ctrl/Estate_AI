# Dashboard/dashboard.py

import os
import sys
import math
import re
import statistics
from pathlib import Path
from typing import List, Dict, Any, Optional

import streamlit as st
from sqlalchemy import select, func
from dotenv import load_dotenv

import requests
from bs4 import BeautifulSoup
import html

# =========================
# Projekt-Root & .env laden
# =========================

BASE_DIR = Path(__file__).resolve().parents[1]  # eine Ebene über /Dashboard
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

# .env aus dem Projektroot laden (lokal)
load_dotenv(BASE_DIR / ".env")

from database.connection import get_session
from database import models
from database.models import Base  # für DB-Init
from database.ingest import ingest_bulk_results
from scraper.sources.rightmove_scraper import scrape_all_sync
# Benchmarks-Seed
from database.seed_benchmarks import seed_all_benchmarks

# =========================
# Analytics API
# =========================

# Auf Streamlit Cloud gibt es KEIN lokales 127.0.0.1:8000.
# Wenn ESTATEAI_API_URL nicht gesetzt ist, gelten Capex/Refurb als "deaktiviert".
API_URL = os.getenv("ESTATEAI_API_URL")


def analytics_available() -> bool:
    """True, wenn ein externes Analytics-Backend konfiguriert ist."""
    return bool(API_URL)


# =========================
# OpenAI-Client für Chat
# =========================

try:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    openai_client = OpenAI(api_key=api_key)
except Exception as e:
    openai_client = None
    print("OpenAI client not available:", e)


# =========================
# DB-Init Helper
# =========================

def ensure_db_initialized() -> None:
    """
    Legt alle Tabellen an, falls sie noch nicht existieren.
    Wichtig für Streamlit Cloud, wo die DB frisch ist.
    Zusätzlich: Seedet Benchmarks (Baukosten, Renovation Modules, Mietspiegel),
    aber nur, wenn die Tabellen leer sind.
    """
    try:
        with get_session() as session:
            bind = session.get_bind()
            Base.metadata.create_all(bind=bind)
            seed_all_benchmarks(session)
    except Exception as e:
        print("DB init failed (ignored):", e)


# =========================
# Helper: DB-Access (Core KPIs)
# =========================

def load_summary() -> Dict[str, Any]:
    """
    Aggregierte KPIs für das Dashboard.
    Trennt zwischen SALE- und RENT-Listings.
    """
    with get_session() as session:
        total_listings = session.scalar(select(func.count(models.Listing.id))) or 0

        total_sale = session.scalar(
            select(func.count(models.Listing.id)).where(models.Listing.listing_type == "sale")
        ) or 0

        total_rent = session.scalar(
            select(func.count(models.Listing.id)).where(models.Listing.listing_type == "rent")
        ) or 0

        max_price_sale = session.scalar(
            select(func.max(models.Listing.price)).where(models.Listing.listing_type == "sale")
        ) or 0

        avg_price_sale = session.scalar(
            select(func.avg(models.Listing.price)).where(models.Listing.listing_type == "sale")
        ) or 0

    return {
        "total_listings": total_listings,
        "total_sale": total_sale,
        "total_rent": total_rent,
        "max_price_sale": max_price_sale,
        "avg_price_sale": avg_price_sale,
    }


def load_distinct_property_types() -> List[str]:
    with get_session() as session:
        stmt = select(models.Listing.property_type).distinct()
        rows = session.execute(stmt).all()
    types = sorted({r[0] for r in rows if r[0]})
    return types


def _basic_distribution(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "avg": None,
            "median": None,
        }
    cleaned = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    if not cleaned:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "avg": None,
            "median": None,
        }
    cleaned.sort()
    return {
        "count": len(cleaned),
        "min": min(cleaned),
        "max": max(cleaned),
        "avg": sum(cleaned) / len(cleaned),
        "median": statistics.median(cleaned),
    }


def load_price_distribution(
    listing_type: Optional[str] = None,
    per_sqm: bool = False,
) -> Dict[str, Any]:
    """
    Liefert Verteilung für Preise (oder Preis/m²) für SALE bzw. RENT.
    """
    with get_session() as session:
        stmt = (
            select(
                models.Listing.price,
                models.Property.floor_area_sqm,
            )
            .join(models.Property, models.Property.id == models.Listing.property_id)
        )
        if listing_type:
            stmt = stmt.where(models.Listing.listing_type == listing_type)

        rows = session.execute(stmt).all()

    values: List[float] = []
    for price, sqm in rows:
        if price is None or price <= 0:
            continue
        if per_sqm:
            if sqm is None or sqm <= 0:
                continue
            values.append(float(price) / float(sqm))
        else:
            values.append(float(price))

    return _basic_distribution(values)


def load_rent_area_stats() -> Dict[str, Any]:
    """
    Stats für Miet-Listings mit Wohnfläche:
    - Anzahl
    - Ø Wohnfläche
    - Ø Miete (PCM)
    - Ø Miete pro m² (PCM)
    """
    with get_session() as session:
        stmt = (
            select(
                models.Listing.price,
                models.Property.floor_area_sqm,
            )
            .join(models.Property, models.Property.id == models.Listing.property_id)
            .where(
                models.Listing.listing_type == "rent",
                models.Listing.price.isnot(None),
                models.Listing.price > 0,
                models.Property.floor_area_sqm.isnot(None),
                models.Property.floor_area_sqm > 0,
            )
        )
        rows = session.execute(stmt).all()

    if not rows:
        return {
            "count": 0,
            "avg_sqm": None,
            "avg_rent_pcm": None,
            "avg_rent_per_sqm_pcm": None,
        }

    prices = [float(r[0]) for r in rows]
    areas = [float(r[1]) for r in rows if r[1] is not None and r[1] > 0]

    count = min(len(prices), len(areas))
    if count == 0:
        return {
            "count": 0,
            "avg_sqm": None,
            "avg_rent_pcm": None,
            "avg_rent_per_sqm_pcm": None,
        }

    prices = prices[:count]
    areas = areas[:count]

    psqm_list = [p / a for p, a in zip(prices, areas) if a > 0]

    return {
        "count": count,
        "avg_sqm": sum(areas) / len(areas),
        "avg_rent_pcm": sum(prices) / len(prices),
        "avg_rent_per_sqm_pcm": sum(psqm_list) / len(psqm_list) if psqm_list else None,
    }


# =========================
# Helper: DB-Access (Listings)
# =========================

def load_listings(
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_beds: Optional[int] = None,
    prop_type: Optional[str] = None,
    listing_type: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Holt Listings aus der DB inkl. Filter.
    Zusätzlich werden Property-Felder (m², Baujahr, EPC, City) gemappt,
    damit der KI-Agent mehr Kontext hat.
    """
    with get_session() as session:
        stmt = (
            select(
                models.Listing.id,
                models.Listing.property_id,
                models.Listing.url,
                models.Listing.price,
                models.Listing.bedrooms,
                models.Listing.bathrooms,
                models.Listing.property_type,
                models.Listing.listing_type,
                models.Listing.description,
                models.Property.floor_area_sqm,
                models.Property.year_built,
                models.Property.energy_rating,
                models.Property.city,
            )
            .join(models.Property, models.Property.id == models.Listing.property_id)
            .order_by(models.Listing.price.desc())
            .limit(limit)
        )

        if min_price is not None:
            stmt = stmt.where(models.Listing.price >= min_price)
        if max_price is not None:
            stmt = stmt.where(models.Listing.price <= max_price)
        if min_beds is not None:
            stmt = stmt.where(models.Listing.bedrooms >= min_beds)
        if prop_type and prop_type != "All":
            stmt = stmt.where(models.Listing.property_type == prop_type)
        if listing_type and listing_type != "All":
            stmt = stmt.where(models.Listing.listing_type == listing_type)

        rows = session.execute(stmt).all()

    data: List[Dict[str, Any]] = []
    for r in rows:
        desc = (r.description or "").replace("\n", " ")
        short_desc = (desc[:200] + "...") if len(desc) > 200 else desc

        floor_area = r.floor_area_sqm
        price_per_sqm = None
        if floor_area and r.price:
            try:
                price_per_sqm = float(r.price) / float(floor_area)
            except Exception:
                price_per_sqm = None

        data.append(
            {
                "id": r.id,
                "property_id": r.property_id,
                "url": r.url,
                "price": r.price,
                "bedrooms": r.bedrooms,
                "bathrooms": r.bathrooms,
                "type": r.property_type,
                "listing_type": r.listing_type,
                "description": short_desc,
                "description_full": desc,
                "floor_area_sqm": floor_area,
                "price_per_sqm": price_per_sqm,
                "year_built": r.year_built,
                "energy_rating": r.energy_rating,
                "city": r.city,
            }
        )
    return data


def load_listing_by_id(listing_id: int) -> Optional[Dict[str, Any]]:
    """
    Holt ein einzelnes Listing nach ID aus der DB inkl. Property-Feldern.
    """
    with get_session() as session:
        stmt = (
            select(
                models.Listing.id,
                models.Listing.property_id,
                models.Listing.url,
                models.Listing.price,
                models.Listing.bedrooms,
                models.Listing.bathrooms,
                models.Listing.property_type,
                models.Listing.listing_type,
                models.Listing.description,
                models.Property.floor_area_sqm,
                models.Property.year_built,
                models.Property.energy_rating,
                models.Property.city,
            )
            .join(models.Property, models.Property.id == models.Listing.property_id)
            .where(models.Listing.id == listing_id)
        )

        row = session.execute(stmt).one_or_none()

    if row is None:
        return None

    desc = (row.description or "").replace("\n", " ")
    short_desc = (desc[:200] + "...") if len(desc) > 200 else desc

    floor_area = row.floor_area_sqm
    price_per_sqm = None
    if floor_area and row.price:
        try:
            price_per_sqm = float(row.price) / float(floor_area)
        except Exception:
            price_per_sqm = None

    return {
        "id": row.id,
        "property_id": row.property_id,
        "url": row.url,
        "price": row.price,
        "bedrooms": row.bedrooms,
        "bathrooms": row.bathrooms,
        "type": row.property_type,
        "listing_type": row.listing_type,
        "description": short_desc,
        "description_full": desc,
        "floor_area_sqm": floor_area,
        "price_per_sqm": price_per_sqm,
        "year_built": row.year_built,
        "energy_rating": row.energy_rating,
        "city": row.city,
    }


def extract_property_ids_from_question(question: str) -> List[int]:
    """
    Versucht IDs aus der Frage zu ziehen, z.B.:
    - "Listing 5"
    - "ID 12"
    - "listing #7"
    """
    matches = re.findall(r"(?:id|listing|#)\s*(\d+)", question, flags=re.IGNORECASE)

    ids: List[int] = []
    for m in matches:
        try:
            ids.append(int(m))
        except ValueError:
            continue

    # Dedupe, Reihenfolge behalten
    return list(dict.fromkeys(ids))


def detect_question_intent(question: str) -> Dict[str, Any]:
    """
    Sehr einfache regelbasierte Intent-Erkennung.
    Liefert Hinweise für den Prompt (Portfolio vs. Listing, m², Rendite etc.).
    """
    q = question.lower()

    intent: Dict[str, Any] = {
        "focus": "portfolio",      # oder "listing"
        "mode": "generic",         # "rent_psqm", "sale_psqm", "yield", "compare_price"
        "listing_ids": extract_property_ids_from_question(question),
    }

    if intent["listing_ids"]:
        intent["focus"] = "listing"

    # m² / Quadratmeter
    sqm_words = ["m²", "sqm", "square meter", "square metre", "quadratmeter", "quadratmeterpreis", "psqm"]
    rent_words = ["miete", "rent", "rental", "pcm"]
    sale_words = ["kauf", "kaufpreis", "purchase", "buy", "verkauf", "price"]

    if any(w in q for w in sqm_words) and any(w in q for w in rent_words):
        intent["mode"] = "rent_psqm"
    elif any(w in q for w in sqm_words) and any(w in q for w in sale_words):
        intent["mode"] = "sale_psqm"
    elif any(w in q for w in ["rendite", "yield", "cap rate", "return on investment", "roi"]):
        intent["mode"] = "yield"
    elif any(w in q for w in ["teuer", "billig", "expensive", "cheap", "overpriced", "underpriced", "fair price"]):
        intent["mode"] = "compare_price"

    return intent


# =========================
# Scraper + Ingest (LOCAL USE)
# =========================

def refresh_data(location: str = "London", pages: int = 1):
    """
    Läuft deinen Scraper + Ingest einmal durch,
    um neue Rightmove-Daten zu holen.
    Hinweis:
    - Für LOCAL DEV gedacht.
    - Auf Streamlit Cloud sollte der Nightly-Job (GitHub) laufen.
    """
    ensure_db_initialized()

    results = scrape_all_sync(location=location, pages=pages)

    total, success, error = ingest_bulk_results(
        results,
        portal="rightmove",
        location_query=f"{location}, pages={pages}",
        listing_type="sale",
    )
    return total, success, error


# =========================
# Bilder von Rightmove holen
# =========================

@st.cache_data(show_spinner=False)
def get_listing_images(url: str) -> List[str]:
    """
    Versucht, eine Liste von Vorschaubildern von der Rightmove-Seite zu holen.
    Sucht zuerst in Meta-Tags, dann in <img>-Tags und gibt mehrere URLs zurück.
    """
    try:
        clean_url = url.split("#")[0]

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        resp = requests.get(clean_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        urls: List[str] = []

        # 1) Meta-Tags (og:image, secure_url, twitter:image)
        meta_candidates = [
            ("meta", {"property": "og:image"}),
            ("meta", {"property": "og:image:secure_url"}),
            ("meta", {"name": "twitter:image"}),
        ]
        for name, attrs in meta_candidates:
            tag = soup.find(name, attrs=attrs)
            if tag and tag.get("content"):
                urls.append(tag["content"])

        # 2) Rightmove-spezifische Gallery-/Hero-Bilder
        for img in soup.find_all("img", attrs={"data-testid": ["gallery-image", "hero-image"]}):
            for attr in ["src", "data-src", "data-lazy-src"]:
                src = img.get(attr)
                if src:
                    urls.append(src)

        # 3) Fallback: alle "vernünftigen" Bilder einsammeln
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if not src:
                continue
            if ("rightmove" in src or "media" in src) and src.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            ):
                urls.append(src)

        # Dedupe, Reihenfolge behalten
        deduped = list(dict.fromkeys(urls))
        return deduped

    except Exception:
        return []


# =========================
# Chat-Kontext bauen
# =========================

def build_chat_context(max_listings: int = 30) -> str:
    """
    Baut einen kompakten Text-Kontext aus der Datenbank:
    - Aggregierte Kennzahlen
    - Preisverteilungen
    - Miet-/m²-Stats
    - Beispiel-Listings inkl. m², Preis/m², EPC, Baujahr, City
    """
    summary = load_summary()
    listings = load_listings(limit=max_listings)

    sale_price = load_price_distribution("sale", per_sqm=False)
    rent_price = load_price_distribution("rent", per_sqm=False)
    sale_psqm = load_price_distribution("sale", per_sqm=True)
    rent_psqm = load_price_distribution("rent", per_sqm=True)
    rent_area = load_rent_area_stats()

    lines: List[str] = []

    # High-Level
    lines.append(
        "High-level database summary:\n"
        f"- Total listings in DB: {summary['total_listings']}\n"
        f"- SALE listings: {summary['total_sale']}\n"
        f"- RENT listings: {summary['total_rent']}\n"
        f"- Max SALE price: £{summary['max_price_sale']:,.0f}\n"
        f"- Average SALE price: £{summary['avg_price_sale']:,.0f}\n"
    )

    # Preisverteilungen
    if sale_price["count"] > 0:
        lines.append(
            "\nSALE price distribution (GBP):\n"
            f"- Count: {sale_price['count']}\n"
            f"- Min:   £{sale_price['min']:,.0f}\n"
            f"- Median: £{sale_price['median']:,.0f}\n"
            f"- Max:   £{sale_price['max']:,.0f}\n"
        )
    if rent_price["count"] > 0:
        lines.append(
            "\nRENT price distribution (PCM, GBP):\n"
            f"- Count: {rent_price['count']}\n"
            f"- Min:   £{rent_price['min']:,.0f}\n"
            f"- Median: £{rent_price['median']:,.0f}\n"
            f"- Max:   £{rent_price['max']:,.0f}\n"
        )

    if sale_psqm["count"] > 0:
        lines.append(
            "\nSALE price per sqm distribution (GBP / sqm):\n"
            f"- Count: {sale_psqm['count']}\n"
            f"- Min:   £{sale_psqm['min']:,.0f}\n"
            f"- Median: £{sale_psqm['median']:,.0f}\n"
            f"- Max:   £{sale_psqm['max']:,.0f}\n"
        )
    if rent_psqm["count"] > 0:
        lines.append(
            "\nRENT price per sqm distribution (PCM, GBP / sqm):\n"
            f"- Count: {rent_psqm['count']}\n"
            f"- Min:   £{rent_psqm['min']:,.2f}\n"
            f"- Median: £{rent_psqm['median']:,.2f}\n"
            f"- Max:   £{rent_psqm['max']:,.2f}\n"
        )

    if rent_area["count"] > 0 and rent_area["avg_rent_per_sqm_pcm"] is not None:
        lines.append(
            "\nPortfolio-level rent/area stats (only listings with known floor area):\n"
            f"- Listings with area: {rent_area['count']}\n"
            f"- Avg floor area: {rent_area['avg_sqm']:.1f} sqm\n"
            f"- Avg rent (PCM): £{rent_area['avg_rent_pcm']:,.0f}\n"
            f"- Avg rent per sqm (PCM): £{rent_area['avg_rent_per_sqm_pcm']:,.2f}\n"
        )

    if not listings:
        lines.append("\nNo individual listings available yet.")
        return "\n".join(lines)

    # Beispiel-Listings
    lines.append(
        "\nSample listings "
        "(id, listing_type, price, bedrooms, bathrooms, floor_sqm, price_per_sqm, city, energy_rating, year_built):"
    )
    for l in listings[:max_listings]:
        price = l["price"]
        price_str = f"£{price:,.0f}" if price is not None and not math.isnan(price) else "n/a"
        sqm = f"{l['floor_area_sqm']:.1f}" if l.get("floor_area_sqm") else "n/a"
        p_sqm = f"£{l['price_per_sqm']:,.0f}" if l.get("price_per_sqm") else "n/a"
        city = l.get("city") or "n/a"
        epc = l.get("energy_rating") or "n/a"
        year = l.get("year_built") or "n/a"

        lines.append(
            f"- id={l['id']}, type={l['type']}, listing_type={l['listing_type']}, "
            f"price={price_str}, bedrooms={l['bedrooms']}, bathrooms={l['bathrooms']}, "
            f"floor_sqm={sqm}, price_per_sqm={p_sqm}, city={city}, "
            f"energy_rating={epc}, year_built={year}"
        )

    return "\n".join(lines)


def build_chat_context_for_question(question: str, max_listings: int = 30) -> str:
    """
    Kombiniert:
    - globale DB-Summary + Verteilungen
    - Sample-Listings
    - explizite Details zu Listings, die in der Frage erwähnt wurden
    - Intent-Hints (Rendite, m², teuer/billig etc.)
    """
    base_context = build_chat_context(max_listings=max_listings)
    intent = detect_question_intent(question)
    focus_ids = intent.get("listing_ids", [])

    lines = [base_context]

    if focus_ids:
        lines.append("\n\nFocus listings mentioned in the question (full details where available):")
        for lid in focus_ids:
            listing = load_listing_by_id(lid)
            if listing:
                price = listing["price"]
                price_str = f"£{price:,.0f}" if price is not None and not math.isnan(price) else "n/a"
                sqm = (
                    f"{listing['floor_area_sqm']:.1f}"
                    if listing.get("floor_area_sqm")
                    else "n/a"
                )
                p_sqm = (
                    f"£{listing['price_per_sqm']:,.0f}"
                    if listing.get("price_per_sqm")
                    else "n/a"
                )
                city = listing.get("city") or "n/a"
                epc = listing.get("energy_rating") or "n/a"
                year = listing.get("year_built") or "n/a"

                lines.append(
                    f"- id={listing['id']}, price={price_str}, "
                    f"bedrooms={listing['bedrooms']}, bathrooms={listing['bathrooms']}, "
                    f"type={listing['type']}, listing_type={listing['listing_type']}, "
                    f"floor_sqm={sqm}, price_per_sqm={p_sqm}, city={city}, "
                    f"energy_rating={epc}, year_built={year}, url={listing['url']}"
                )
            else:
                lines.append(f"- id={lid} (not found in DB)")

    # Intent-Hints für das Modell
    q_lower = question.lower()
    intent_hints: List[str] = []

    if intent["mode"] == "rent_psqm":
        intent_hints.append(
            "- The user is asking about rent per square metre (PCM). "
            "Use the rent-per-sqm statistics from the context where available. "
            "If only rent and area are known for individual listings, compute "
            "rent_per_sqm = rent_pcm / floor_area_sqm explicitly."
        )
    elif intent["mode"] == "sale_psqm":
        intent_hints.append(
            "- The user is asking about purchase price per square metre. "
            "Use price_per_sqm where available and show at least an average value. "
            "Formula: price_per_sqm = purchase_price / floor_area_sqm."
        )
    elif intent["mode"] == "yield":
        intent_hints.append(
            "- The user is asking about rental yield / ROI. "
            "Use yields based on purchase price and annual net rent. "
            "Formula: yield = annual_net_rent / purchase_price. "
            "If important inputs (price, rent, opex, holding period) are missing, "
            "ask up to two focused follow-up questions before calculating."
        )
    elif intent["mode"] == "compare_price":
        intent_hints.append(
            "- The user is asking whether a listing or group of listings is expensive or cheap. "
            "Compare the price (and price per sqm where available) to the distributions "
            "in the context (min / median / max). Talk in relative terms (+/- %, "
            "above/below median) instead of vague statements."
        )

    if any(w in q_lower for w in ["tabelle", "table", "übersicht", "matrix"]):
        intent_hints.append(
            "- Present the key numbers in a compact Markdown table (max ~10 rows) "
            "in addition to your explanation."
        )

    if intent_hints:
        lines.append("\n\nIntent hints for you as the model:")
        lines.extend(intent_hints)

    return "\n".join(lines)


def ask_chat_model(
    question: str,
    context: str,
    stream_placeholder: Optional[st.delta_generator.DeltaGenerator] = None,
) -> str:
    """
    Fragt das OpenAI-Modell.
    - Nutzt einen starken System-Prompt für Real-Estate-Analysen.
    - Kann optional token-weise in ein Streamlit-Placeholder streamen.
    """
    if openai_client is None:
        msg = (
            "The AI assistant is not configured yet (missing OpenAI client or API key).\n"
            "Please set OPENAI_API_KEY (e.g. in Streamlit Secrets) and make sure the "
            "'openai' package is installed."
        )
        if stream_placeholder is not None:
            stream_placeholder.markdown(msg)
        return msg

    system_content = (
        "You are EstateAI, a senior real estate & construction investment analyst. "
        "You see a snapshot of Rightmove listings stored in a structured database.\n\n"
        "DATA YOU SEE IN THE CONTEXT:\n"
        "- Portfolio-level stats (counts, min/median/max prices, averages).\n"
        "- Distributions for SALE and RENT prices and price-per-sqm where available.\n"
        "- Sample listings with: id, listing_type, price, bedrooms, bathrooms, floor_area_sqm, "
        "  price_per_sqm, city, energy_rating, year_built, URL.\n\n"
        "CRITICAL RULES:\n"
        "1) For database-based numbers (portfolio stats, listing prices, rents, m² etc.) "
        "   only use numeric values that explicitly appear in the provided context. "
        "   Never invent concrete prices, rents, yields, or addresses that are not present.\n"
        "2) For purely hypothetical investment questions where the user gives all numbers "
        "   (purchase price, rent, opex, growth, holding period, etc.), you MAY compute "
        "   yields and cash flows based on those user-provided numbers even if they are "
        "   not in the database context.\n"
        "3) If important numeric inputs are missing (e.g. purchase price, expected rent, "
        "   opex, holding period, target yield), do NOT guess. Instead:\n"
        "   - Explain briefly which data is missing.\n"
        "   - Ask up to TWO very concrete follow-up questions to get that data.\n"
        "   - Only then perform calculations.\n"
        "4) Answer in the same language as the user's question (German or English).\n\n"
        "OUTPUT STRUCTURE (unless the user explicitly asks for a different format):\n"
        "1. Short answer (1–3 sentences) summarising the result.\n"
        "2. Key numbers\n"
        "   - Bullet points OR a compact Markdown table (max ~10 rows).\n"
        "   - Always show formulas for yields, price-per-sqm and other ratios you compute.\n"
        "3. Interpretation & investor view\n"
        "   - How attractive is this (risk/return, upside/downside)?\n"
        "   - How does it compare to the rest of the portfolio (median, min/max, psqm)?\n\n"
        "TABLES:\n"
        "- You may output Markdown tables. They will be rendered nicely in the UI.\n"
        "- Prefer small, focused tables over raw dumps of all listings.\n"
    )

    messages = [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": (
                f"Database context (Rightmove scrape):\n{context}\n\n"
                f"User question:\n{question}"
            ),
        },
    ]

    # Streaming für „typing effect“
    if stream_placeholder is None:
        completion = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.15,
            messages=messages,
        )
        return completion.choices[0].message.content.strip()

    full_answer = ""
    stream = openai_client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0.15,
        messages=messages,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            full_answer += delta
            stream_placeholder.markdown(full_answer)

    return full_answer.strip()


# =========================
# Streamlit Tabs
# =========================

def render_listings_tab():
    # --- Summary KPIs (ohne Scraper-Button) ---
    summary = load_summary()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("SALE Listings", summary["total_sale"])
    col2.metric("RENT Listings", summary["total_rent"])
    col3.metric("Max Price (SALE, GBP)", f"{summary['max_price_sale']:,.0f}")
    col4.metric("Avg Price (SALE, GBP)", f"{summary['avg_price_sale']:,.0f}")

    st.markdown("---")

    # --- Filter ---
    st.subheader("🔍 Filter")

    prop_types = ["All"] + load_distinct_property_types()

    col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)

    min_price = col_f1.number_input("Min Price (GBP)", value=0.0, step=1_000_000.0)
    max_price = col_f2.number_input("Max Price (GBP)", value=100_000_000.0, step=1_000_000.0)
    min_beds = col_f3.number_input("Min Bedrooms", value=0, step=1)
    prop_type = col_f4.selectbox("Property Type", options=prop_types)
    listing_type_filter = col_f5.selectbox("Listing Type", options=["All", "sale", "rent"])

    st.markdown("---")

    # --- Listings-Table ---
    listings = load_listings(
        min_price=min_price or None,
        max_price=max_price or None,
        min_beds=min_beds or None,
        prop_type=prop_type,
        listing_type=listing_type_filter if listing_type_filter != "All" else None,
        limit=200,
    )

    tab_overview, tab_capex, tab_refurb, tab_insights = st.tabs(
        ["📄 Listings Overview", "🔧 Renovation & Capex", "🏗️ Refurb & Risk", "📈 Construction Insights"]
    )

    with tab_overview:
        st.subheader(f"📄 Listings (Treffer: {len(listings)})")

        if not listings:
            st.info("Keine Listings gefunden – eventuell Filter anpassen oder Scraper/Nightly-Job laufen lassen.")
            return

        table_data = [
            {
                "ID": l["id"],
                "Property ID": l["property_id"],
                "Listing Type": l["listing_type"],
                "Price (GBP)": l["price"],
                "Bedrooms": l["bedrooms"],
                "Bathrooms": l["bathrooms"],
                "Type": l["type"],
                "Floor Area (sqm)": l.get("floor_area_sqm"),
                "Price per sqm (GBP)": l.get("price_per_sqm"),
                "City": l.get("city"),
                "EPC": l.get("energy_rating"),
                "Year Built": l.get("year_built"),
                "URL": l["url"],
                "Description": l["description"],
            }
            for l in listings
        ]
        st.dataframe(table_data, use_container_width=True)

        # --- Detail-View ---
        st.markdown("### 🔎 Listing Details")

        col_left, col_right = st.columns([1, 2])

        with col_left:
            ids = [l["id"] for l in listings]
            selected_id = st.selectbox("Listing ID auswählen", ids)
            selected = next(l for l in listings if l["id"] == selected_id)

            # in Session packen, damit Capex/Refurb Tabs Zugriff haben
            st.session_state["selected_property"] = selected

            st.write(f"**URL:** [{selected['url']}]({selected['url']})")
            if selected["price"] is not None and not math.isnan(selected["price"]):
                st.write(f"**Price:** £{selected['price']:,.0f}")
            else:
                st.write("**Price:** n/a")
            st.write(f"**Listing Type:** {selected['listing_type']}")
            st.write(f"**Bedrooms:** {selected['bedrooms']}")
            st.write(f"**Bathrooms:** {selected['bathrooms']}")
            st.write(f"**Type:** {selected['type']}")
            st.write(f"**Property ID:** {selected['property_id']}")
            if selected.get("floor_area_sqm"):
                st.write(f"**Floor Area:** {selected['floor_area_sqm']:.1f} sqm")
            if selected.get("price_per_sqm"):
                st.write(f"**Price per sqm:** £{selected['price_per_sqm']:,.0f}")
            if selected.get("city"):
                st.write(f"**City:** {selected['city']}")
            if selected.get("energy_rating"):
                st.write(f"**Energy Rating (EPC):** {selected['energy_rating']}")
            if selected.get("year_built"):
                st.write(f"**Year Built:** {selected['year_built']}")

        with col_right:
            # Bilder – einfacher "Carousel"-Viewer mit Pfeilen
            image_urls = get_listing_images(selected["url"])

            if image_urls:
                state_key = f"img_idx_{selected['id']}"

                if state_key not in st.session_state:
                    st.session_state[state_key] = 0

                nav_left, nav_center, nav_right = st.columns([1, 4, 1])
                with nav_left:
                    prev_clicked = st.button("◀", key=f"prev_{selected['id']}_prev")
                with nav_right:
                    next_clicked = st.button("▶", key=f"next_{selected['id']}_next")

                if prev_clicked:
                    st.session_state[state_key] = (st.session_state[state_key] - 1) % len(image_urls)
                if next_clicked:
                    st.session_state[state_key] = (st.session_state[state_key] + 1) % len(image_urls)

                current_idx = st.session_state[state_key]
                current_img = image_urls[current_idx]

                st.image(current_img, use_container_width=True)
                st.caption(f"Image {current_idx + 1} of {len(image_urls)} (Rightmove)")
            else:
                st.info("No image preview available for this listing.")

            # Beschreibung
            st.write("**Full Description:**")
            st.write(selected["description_full"])

    # ==== TAB 2: Renovation & Capex Copilot ====
    with tab_capex:
        st.subheader("🔧 Renovation & Capex Copilot")

        if not analytics_available():
            st.info(
                "Die Capex-Analyse ist derzeit nur verfügbar, wenn ein externes "
                "EstateAI-Backend (FastAPI) über `ESTATEAI_API_URL` konfiguriert ist.\n\n"
                "In dieser Streamlit-Cloud-Version werden hier keine Berechnungen ausgeführt."
            )
        elif "selected_property" not in st.session_state:
            st.info("Bitte zuerst im Tab 'Listings Overview' ein Listing auswählen.")
        else:
            prop = st.session_state["selected_property"]

            st.markdown(f"**Ausgewähltes Listing:** ID {prop['id']} – Property ID {prop['property_id']}")
            st.write(f"Listing Type: {prop['listing_type']}")
            st.write(f"Preis: £{prop['price']:,.0f}" if prop["price"] else "Preis: n/a")

            spec_level = st.selectbox("Ausbau-Standard", ["basic", "standard", "premium"], index=1)

            st.markdown("**Renovation Modules** (IDs müssen mit deiner DB übereinstimmen)")
            kitchen = st.checkbox("Küche komplett (ID 1)")
            bathroom = st.checkbox("Bad Kernsanierung (ID 2)")
            windows = st.checkbox("Fenster & Dämmung (ID 3)")

            module_ids: List[int] = []
            if kitchen:
                module_ids.append(1)
            if bathroom:
                module_ids.append(2)
            if windows:
                module_ids.append(3)

            current_rent_pcm = st.number_input("Aktuelle Miete (PCM)", min_value=0.0, value=0.0, step=50.0)
            target_rent_pcm = st.number_input("Zielmiete nach Refurb (PCM)", min_value=0.0, value=0.0, step=50.0)
            opex_per_year = st.number_input("OPEX / Jahr (£)", min_value=0.0, value=0.0, step=500.0)

            if st.button("Capex & Rendite berechnen"):
                payload = {
                    "property_id": int(prop["property_id"]),
                    "region": "London",
                    "building_type": "residential",
                    "spec_level": spec_level,
                    "renovation_module_ids": module_ids or None,
                    "current_rent_pcm": current_rent_pcm or None,
                    "target_rent_pcm": target_rent_pcm or None,
                    "opex_per_year": opex_per_year or None,
                    "purchase_price": prop.get("price"),
                }

                try:
                    resp = requests.post(f"{API_URL}/analytics/capex", json=payload, timeout=10)
                    if resp.status_code != 200:
                        st.error(f"Fehler: {resp.json().get('detail')}")
                    else:
                        data = resp.json()
                        st.success("Ergebnis")
                        st.write(f"**Total Capex:** £{data['total_capex']:,.0f}")
                        st.write(f"**Capex / m²:** £{data['capex_per_sqm']:,.0f}")
                        if data["new_rent_pcm"]:
                            st.write(f"**Neue Miete (PCM):** £{data['new_rent_pcm']:,.0f}")
                        if data["new_yield"] is not None:
                            st.write(f"**Neue (simple) Netto-Rendite:** {data['new_yield']*100:.2f}%")
                except Exception as e:
                    st.error(f"API-Fehler: {e}")

    # ==== TAB 3: Refurb-Rating & Risiko ====
    with tab_refurb:
        st.subheader("🏗️ Refurb Rating & Energy Risk")

        if not analytics_available():
            st.info(
                "Die Refurb- & Energierisiko-Analyse ist derzeit nur mit einem externen "
                "EstateAI-Backend verfügbar (`ESTATEAI_API_URL`).\n\n"
                "In dieser Streamlit-Cloud-Version werden dafür keine API-Calls ausgeführt."
            )
        elif "selected_property" not in st.session_state:
            st.info("Bitte zuerst im Tab 'Listings Overview' ein Listing auswählen.")
        else:
            prop = st.session_state["selected_property"]
            st.markdown(f"**Listing ID:** {prop['id']} – **Property ID:** {prop['property_id']}")

            if st.button("Refurb & Risiko berechnen"):
                try:
                    resp = requests.get(f"{API_URL}/analytics/refurb/{int(prop['property_id'])}", timeout=10)
                    if resp.status_code != 200:
                        st.error(f"Fehler: {resp.json().get('detail')}")
                    else:
                        data = resp.json()
                        st.write(f"**Refurb-Intensity:** {data['refurb_intensity']}")
                        st.write(f"**Energy Risk Score:** {data['energy_risk_score']:.1f} / 100")
                except Exception as e:
                    st.error(f"API-Fehler: {e}")

    # ==== TAB 4: Construction-Insights ====
    with tab_insights:
        st.subheader("📈 Construction & Cost Insights")
        st.write(
            "Hier kannst du später Baukosten-Indizes, Average Capex/m², "
            "Verteilung nach Baujahr, Energieklassen usw. visualisieren."
        )
        st.info("Datenbasis dafür liegt in den Tabellen construction_cost_benchmarks & construction_indices.")


def render_chat_tab():
    st.subheader("💬 EstateAI – AI Assistant")

    st.markdown(
        "Stell Fragen zu den aktuell in der Datenbank gespeicherten Immobilien oder zu "
        "spezifischen Investment-Szenarien.\n\n"
        "- Beispiele: *„Wie ist die durchschnittliche Miete pro m² in London?“*, "
        "*„Ist Listing 5 im Vergleich zu den anderen teuer?“*, "
        "*„Wie hoch wäre die Brutto-Mietrendite bei Kaufpreis 500.000 £ und Miete 2.000 £ pcm?“*, "
        "*„Erstelle mir eine kleine Tabelle mit den wichtigsten Kennzahlen für die teuersten Listings.“*"
    )

    # Warnung, falls keine Listings vorhanden
    summary_for_chat = load_summary()
    if summary_for_chat["total_listings"] == 0:
        st.warning(
            "Aktuell sind noch keine Listings in der Datenbank. "
            "Bitte zuerst den Nightly-Scraper laufen lassen (GitHub) "
            "oder lokal einmal scrapen."
        )
        return

    if openai_client is None:
        st.warning(
            "OPENAI_API_KEY ist nicht gesetzt oder der Client konnte nicht initialisiert werden.\n"
            "Bitte den API Key in den Streamlit Secrets oder der .env-Datei hinterlegen."
        )

    # Chat-History initialisieren
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []

    # Chat zurücksetzen
    reset_col, _ = st.columns([1, 5])
    with reset_col:
        if st.button("🧹 Chat zurücksetzen"):
            st.session_state["chat_messages"] = []
            st.rerun()

    # -------- Chatfenster mit Scroll --------
    messages_html = ""
    for msg in st.session_state["chat_messages"]:
        role_label = "You" if msg["role"] == "user" else "EstateAI"
        align = "flex-end" if msg["role"] == "user" else "flex-start"
        bg = "#1f2937" if msg["role"] == "user" else "#020617"

        safe_content = html.escape(msg["content"])

        messages_html += f"""
<div style="display:flex; justify-content:{align}; margin-bottom:0.35rem;">
  <div style="max-width:80%;">
    <div style="font-size:0.7rem; opacity:0.7; margin-bottom:0.15rem;">
      {role_label}
    </div>
    <div style="
        background:{bg};
        padding:0.5rem 0.75rem;
        border-radius:0.75rem;
        white-space:pre-wrap;
        font-size:0.9rem;
        line-height:1.3;
    ">
      {safe_content}
    </div>
  </div>
</div>
"""

    st.markdown(
        f"""
<div style="
    height: 420px;
    overflow-y: auto;
    border-radius: 0.75rem;
    border: 1px solid #334155;
    padding: 0.75rem;
    background-color: #020617;
    margin-bottom: 0.5rem;
">
    {messages_html}
</div>
""",
        unsafe_allow_html=True,
    )

    # -------- Eingabefeld --------
    prompt = st.chat_input("Ask a question about these listings or an investment scenario…")

    if prompt:
        st.session_state["chat_messages"].append({"role": "user", "content": prompt})

        # Placeholder für Streaming-Antwort (typing effect)
        assistant_placeholder = st.empty()

        with st.spinner("Analyzing the current portfolio and database context…"):
            context = build_chat_context_for_question(prompt)
            answer = ask_chat_model(prompt, context, stream_placeholder=assistant_placeholder)

        # finale Antwort in History speichern
        st.session_state["chat_messages"].append({"role": "assistant", "content": answer})

        st.rerun()


# =========================
# Haupt-Entry
# =========================

def main():
    # Tabellen anlegen, falls sie fehlen (wichtig in der Cloud)
    ensure_db_initialized()

    st.set_page_config(
        page_title="EstateAI – Investor Dashboard",
        layout="wide",
    )

    st.title("🏡 EstateAI – Investor Dashboard (Rightmove MVP)")

    st.markdown(
        "Dieses Dashboard zeigt echte Rightmove-Daten, "
        "gescraped mit unserem Playwright-Scraper und in einer strukturierten Datenbank gespeichert.\n\n"
        "Die Daten kommen entweder aus deinem lokalen Scraper-Run oder dem automatischen Nightly-Scraper."
    )

    tab_listings, tab_chat = st.tabs(["Listings", "AI Assistant"])

    with tab_listings:
        render_listings_tab()

    with tab_chat:
        render_chat_tab()


if __name__ == "__main__":
    main()
