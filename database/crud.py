"""
High-level CRUD & Upsert-Funktionen für das EstateAI-Datenmodell.

Ziel:
- Scraper gibt ein dict zurück → hier wird es in die Pyramiden-DB gemappt.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models


# -------------------------------------------------------------
# Helper: Preis-Parsing "£27,500,000" -> 27500000.0
# -------------------------------------------------------------
def parse_price_to_float(price_str: Optional[str]) -> Optional[float]:
    if not price_str:
        return None
    try:
        cleaned = price_str.replace("£", "").replace(",", "").strip()
        # Manche Rightmove-Strings enthalten noch "Guide price" etc.
        digits = ""
        for ch in cleaned:
            if ch.isdigit() or ch == ".":
                digits += ch
            elif digits:
                # break when non-digit after we already collected some digits
                break
        if not digits:
            return None
        return float(digits)
    except Exception:
        return None


def parse_int_safe(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


# -------------------------------------------------------------
# MARKETS & SUBMARKETS
# -------------------------------------------------------------
def get_or_create_market(
    session: Session,
    name: str,
    country: str = "UK",
    code: Optional[str] = None,
) -> models.Market:
    stmt = select(models.Market).where(models.Market.name == name)
    if code:
        stmt = stmt.where(models.Market.code == code)

    market = session.execute(stmt).scalar_one_or_none()
    if market:
        return market

    market = models.Market(name=name, country=country, code=code)
    session.add(market)
    session.flush()  # assign id
    return market


def get_or_create_submarket(
    session: Session,
    market: models.Market,
    name: str,
    postcode_prefix: Optional[str] = None,
) -> models.Submarket:
    stmt = select(models.Submarket).where(
        models.Submarket.market_id == market.id,
        models.Submarket.name == name,
    )
    if postcode_prefix:
        stmt = stmt.where(models.Submarket.postcode_prefix == postcode_prefix)

    sub = session.execute(stmt).scalar_one_or_none()
    if sub:
        return sub

    sub = models.Submarket(
        market_id=market.id,
        name=name,
        postcode_prefix=postcode_prefix,
    )
    session.add(sub)
    session.flush()
    return sub


# -------------------------------------------------------------
# PROPERTY
# -------------------------------------------------------------
def get_or_create_property(
    session: Session,
    full_address: str,
    postcode: Optional[str] = None,
    city: Optional[str] = None,
    submarket: Optional[models.Submarket] = None,
    property_type: Optional[str] = None,
    bedrooms: Optional[int] = None,
    bathrooms: Optional[int] = None,
) -> models.Property:
    """
    Identifiziert Properties aktuell primär über (full_address, postcode).
    Für Pitch reicht das. Später kann man hier Geo/Hashing ergänzen.
    """
    stmt = select(models.Property).where(models.Property.full_address == full_address)
    if postcode:
        stmt = stmt.where(models.Property.postcode == postcode)

    prop = session.execute(stmt).scalar_one_or_none()
    if prop:
        # Basisdaten ggf. auffrischen
        updated = False
        if property_type and not prop.property_type:
            prop.property_type = property_type
            updated = True
        if bedrooms is not None and prop.bedrooms is None:
            prop.bedrooms = bedrooms
            updated = True
        if bathrooms is not None and prop.bathrooms is None:
            prop.bathrooms = bathrooms
            updated = True
        if city and not prop.city:
            prop.city = city
            updated = True
        if submarket and not prop.submarket_id:
            prop.submarket_id = submarket.id
            updated = True
        if updated:
            prop.last_seen_at = datetime.utcnow()
        return prop

    prop = models.Property(
        full_address=full_address,
        postcode=postcode,
        city=city,
        submarket_id=submarket.id if submarket else None,
        property_type=property_type,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
    )
    session.add(prop)
    session.flush()
    return prop


# -------------------------------------------------------------
# SCRAPE RUNS
# -------------------------------------------------------------
def create_scrape_run(
    session: Session,
    portal: str = "rightmove",
    location_query: Optional[str] = None,
) -> models.ScrapeRun:
    run = models.ScrapeRun(
        portal=portal,
        location_query=location_query,
        started_at=datetime.utcnow(),
        status="running",
    )
    session.add(run)
    session.flush()
    return run


def finish_scrape_run(
    session: Session,
    run: models.ScrapeRun,
    total_listings: int,
    success_count: int,
    error_count: int,
    status: str = "success",
) -> None:
    run.total_listings = total_listings
    run.success_count = success_count
    run.error_count = error_count
    run.status = status
    run.finished_at = datetime.utcnow()
    session.flush()


# -------------------------------------------------------------
# LISTING & RAW_SCRAPE from Scraper-Dict
# -------------------------------------------------------------
def upsert_listing_from_scrape(
    session: Session,
    scraped: Dict[str, Any],
    run: Optional[models.ScrapeRun] = None,
    portal: str = "rightmove",
    listing_type: str = "sale",
    raw_text: Optional[str] = None,
    raw_meta: Optional[str] = None,
) -> models.Listing:
    """
    Erwartet ein dict in etwa wie:

        {
          "url": "...",
          "title": "...",
          "price": "£27,500,000",
          "address": "...",
          "description": "...",
          "bedrooms": "10",
          "bathrooms": "7",
          "property_type": "House",
          "source": "v4.7_textparse",
        }

    + optional raw_text = body_text aus dem Scraper.
    """

    url = scraped.get("url")
    if not url:
        raise ValueError("scraped['url'] is required")

    address = scraped.get("address") or scraped.get("title") or url
    full_address = address
    # Sehr simple Postcode-Heuristik (z.B. "W11", "SW1A 1AA")
    postcode = None
    parts = address.split(",")
    if parts:
        candidate = parts[-1].strip()
        if len(candidate) <= 8:  # grobe Heuristik
            postcode = candidate or None

    # Noch keine echte City-Erkennung – das kannst du später ausbauen
    city = None

    # Property-Level-Infos vorbereiten
    bedrooms_int = parse_int_safe(scraped.get("bedrooms"))
    bathrooms_int = parse_int_safe(scraped.get("bathrooms"))
    property_type = scraped.get("property_type")

    # Aktuell: Market/Submarket optional/leer – später kannst du hier Mapping bauen
    market = None
    submarket = None
    # Beispiel: London-Hardcode
    if "London" in address:
        market = get_or_create_market(session, name="London", country="UK", code="LON")
        # Submarket könnte man über postcode machen (z.B. "W11")
        if postcode:
            submarket_name = f"{postcode} area"
            submarket = get_or_create_submarket(
                session,
                market=market,
                name=submarket_name,
                postcode_prefix=postcode,
            )

    prop = get_or_create_property(
        session,
        full_address=full_address,
        postcode=postcode,
        city=city,
        submarket=submarket,
        property_type=property_type,
        bedrooms=bedrooms_int,
        bathrooms=bathrooms_int,
    )

    # Preis & Felder für Listing
    price_float = parse_price_to_float(scraped.get("price"))
    description = scraped.get("description")

    # Prüfen, ob es schon ein Listing für (property, url, portal) gibt
    stmt = select(models.Listing).where(
        models.Listing.property_id == prop.id,
        models.Listing.url == url,
        models.Listing.portal == portal,
    )
    listing = session.execute(stmt).scalar_one_or_none()

    now = datetime.utcnow()

    if listing:
        listing.price = price_float
        listing.currency = "GBP"
        listing.bedrooms = bedrooms_int
        listing.bathrooms = bathrooms_int
        listing.property_type = property_type or listing.property_type
        listing.description = description or listing.description
        listing.last_seen_at = now
        if run:
            listing.scrape_run_id = run.id
    else:
        listing = models.Listing(
            property_id=prop.id,
            scrape_run_id=run.id if run else None,
            portal=portal,
            external_id=None,  # könntest du später aus der URL parsen
            url=url,
            listing_type=listing_type,
            status="active",
            tenure=None,
            price=price_float,
            currency="GBP",
            bedrooms=bedrooms_int,
            bathrooms=bathrooms_int,
            property_type=property_type,
            scraped_at=now,
            first_seen_at=now,
            last_seen_at=now,
            description=description,
        )
        session.add(listing)
        session.flush()

    # RawScrape optional speichern
    if raw_text or raw_meta:
        raw = models.RawScrape(
            listing_id=listing.id,
            scraped_at=now,
            raw_text=raw_text,
            raw_meta=raw_meta,
        )
        session.add(raw)

    session.flush()
    return listing
