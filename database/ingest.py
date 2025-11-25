# database/ingest.py

import re
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

from sqlalchemy import select

from database.connection import get_session
from database import models


# ----------------------------------------------------------
# Helper: Parsing / Normalisierung
# ----------------------------------------------------------

def _parse_price(price_raw: Any) -> Optional[float]:
    """
    Erwartet z.B.:
    - '£18,000,000'
    - '18000000'
    - None
    und gibt float oder None zurück.
    """
    if price_raw is None:
        return None

    s = str(price_raw)
    s = re.sub(r"[^\d\.]", "", s)
    if not s:
        return None

    try:
        return float(s)
    except Exception:
        return None


def _parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    s = re.sub(r"[^\d]", "", str(value))
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


# ----------------------------------------------------------
# Ingest: Liste von Scraper-Resultaten → DB
# ----------------------------------------------------------

def ingest_bulk_results(
    results: List[Dict[str, Any]],
    portal: str,
    location_query: str,
    listing_type: str = "sale",
) -> Tuple[int, int, int]:
    """
    Nimmt die Output-Liste deines Scrapers (rightmove_scraper.scrape_all_sync)
    und schreibt sie in:
    - ScrapeRun
    - Property
    - Listing
    - RawScrape

    Gibt zurück: (total, success, error)
    """
    total = len(results)
    success = 0
    error = 0

    with get_session() as session:
        # ---------- ScrapeRun anlegen ----------
        scrape_run = models.ScrapeRun(
            portal=portal,
            location_query=location_query,
            started_at=datetime.utcnow(),
            status="running",
            total_listings=total,
        )
        session.add(scrape_run)
        session.flush()  # ID holen

        for row in results:
            url = row.get("url")
            if not url:
                error += 1
                continue

            try:
                # --------- numerische Felder parsen ---------
                price = _parse_price(row.get("price"))
                bedrooms = _parse_int(row.get("bedrooms"))
                bathrooms = _parse_int(row.get("bathrooms"))

                floor_area_sqm = row.get("floor_area_sqm")
                year_built = row.get("year_built")
                energy_rating = row.get("energy_rating")
                refurb_intensity = row.get("refurb_intensity")

                title = row.get("title")
                address = row.get("address") or title or url
                description = row.get("description") or ""
                property_type = row.get("property_type")

                # --------- Duplikat-Check nach URL ---------
                existing_listing = session.execute(
                    select(models.Listing).where(models.Listing.url == url)
                ).scalar_one_or_none()

                if existing_listing:
                    # Listing updaten
                    if price is not None:
                        existing_listing.price = price
                    if bedrooms is not None:
                        existing_listing.bedrooms = bedrooms
                    if bathrooms is not None:
                        existing_listing.bathrooms = bathrooms
                    existing_listing.last_seen_at = datetime.utcnow()
                    existing_listing.scrape_run = scrape_run

                    # Property ergänzen
                    prop = existing_listing.property
                    if prop:
                        if floor_area_sqm is not None and not prop.floor_area_sqm:
                            prop.floor_area_sqm = floor_area_sqm
                        if year_built is not None and not prop.year_built:
                            prop.year_built = year_built
                        if energy_rating and not prop.energy_rating:
                            prop.energy_rating = energy_rating
                        if refurb_intensity and not prop.refurb_intensity:
                            prop.refurb_intensity = refurb_intensity
                        prop.last_seen_at = datetime.utcnow()

                    success += 1
                    continue

                # --------- Property finden oder neu anlegen ---------
                existing_property = session.execute(
                    select(models.Property).where(models.Property.full_address == address)
                ).scalar_one_or_none()

                if existing_property:
                    prop = existing_property
                    if property_type and not prop.property_type:
                        prop.property_type = property_type
                    if bedrooms is not None and not prop.bedrooms:
                        prop.bedrooms = bedrooms
                    if bathrooms is not None and not prop.bathrooms:
                        prop.bathrooms = bathrooms
                    if floor_area_sqm is not None and not prop.floor_area_sqm:
                        prop.floor_area_sqm = floor_area_sqm
                    if year_built is not None and not prop.year_built:
                        prop.year_built = year_built
                    if energy_rating and not prop.energy_rating:
                        prop.energy_rating = energy_rating
                    if refurb_intensity and not prop.refurb_intensity:
                        prop.refurb_intensity = refurb_intensity

                    prop.last_seen_at = datetime.utcnow()

                else:
                    # Neues Property
                    prop = models.Property(
                        full_address=address,
                        postcode=None,
                        city=None,
                        property_type=property_type,
                        bedrooms=bedrooms,
                        bathrooms=bathrooms,
                        floor_area_sqm=floor_area_sqm,
                        year_built=year_built,
                        is_new_build=False,
                        energy_rating=energy_rating,
                        refurb_intensity=refurb_intensity,
                    )
                    session.add(prop)
                    session.flush()  # ID holen

                # --------- Listing anlegen ---------
                listing = models.Listing(
                    property_id=prop.id,
                    scrape_run_id=scrape_run.id,
                    portal=portal,
                    external_id=None,
                    url=url,
                    listing_type=listing_type,
                    status="active",
                    tenure=None,
                    price=price,
                    currency="GBP",
                    bedrooms=bedrooms,
                    bathrooms=bathrooms,
                    property_type=property_type,
                    description=description,
                    first_seen_at=datetime.utcnow(),
                    last_seen_at=datetime.utcnow(),
                )
                session.add(listing)
                session.flush()

                # --------- RawScrape speichern ---------
                raw_text = row.get("raw_text") or description
                raw_html = row.get("raw_html")
                raw_meta = row.get("raw_meta")

                raw = models.RawScrape(
                    listing_id=listing.id,
                    scraped_at=datetime.utcnow(),
                    raw_text=raw_text,
                    raw_html=raw_html,
                    raw_meta=raw_meta,
                )
                session.add(raw)

                success += 1

            except Exception:
                error += 1

        # ScrapeRun finalisieren
        scrape_run.finished_at = datetime.utcnow()
        scrape_run.success_count = success
        scrape_run.error_count = error
        scrape_run.status = "success" if error == 0 else "completed_with_errors"

        session.commit()

    return total, success, error

