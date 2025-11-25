# pipelines/build_rent_benchmarks.py

from datetime import datetime

from sqlalchemy import select, func

from database.connection import get_session
from database import models


def build_rent_benchmarks(min_listings_per_bucket: int = 5) -> int:
    """
    Aggregiert Mietdaten aus listings (listing_type='rent') in die Tabelle rent_benchmarks.

    Bucket-Logik:
    - city
    - submarket_id (falls vorhanden)
    - bedrooms
    - property_type

    rent_psqm = Miete_pcm / floor_area_sqm

    min_listings_per_bucket:
        nur Buckets mit genügend Datenpunkten werden gespeichert.
    """
    with get_session() as session:
        # Alte Benchmarks erstmal löschen (voller Rebuild)
        session.query(models.RentBenchmark).delete()

        # JOIN: Listing (rent) + Property (für m², city, submarket_id)
        stmt = (
            select(
                models.Property.city.label("city"),
                models.Property.submarket_id.label("submarket_id"),
                models.Listing.bedrooms.label("bedrooms"),
                models.Listing.property_type.label("property_type"),
                func.min(models.Listing.price / models.Property.floor_area_sqm).label("rent_psqm_min"),
                func.max(models.Listing.price / models.Property.floor_area_sqm).label("rent_psqm_max"),
                func.count(models.Listing.id).label("n"),
            )
            .join(models.Property, models.Listing.property_id == models.Property.id)
            .where(
                models.Listing.listing_type == "rent",
                models.Listing.price.isnot(None),
                models.Property.floor_area_sqm.isnot(None),
                models.Property.floor_area_sqm > 0,
            )
            .group_by(
                models.Property.city,
                models.Property.submarket_id,
                models.Listing.bedrooms,
                models.Listing.property_type,
            )
        )

        rows = session.execute(stmt).all()

        created = 0
        now = datetime.utcnow()

        for row in rows:
            city = row.city or "Unknown"
            submarket_id = row.submarket_id
            bedrooms = row.bedrooms
            property_type = row.property_type
            rent_psqm_min = float(row.rent_psqm_min) if row.rent_psqm_min is not None else None
            rent_psqm_max = float(row.rent_psqm_max) if row.rent_psqm_max is not None else None
            n = row.n or 0

            if n < min_listings_per_bucket:
                # zu wenig Daten → Bucket überspringen
                continue

            rb = models.RentBenchmark(
                country="UK",
                city=city,
                submarket_id=submarket_id,
                bedrooms=bedrooms,
                property_type=property_type,
                rent_psqm_min=rent_psqm_min,
                rent_psqm_max=rent_psqm_max,
                currency="GBP",
                source="rightmove_rent_scraper_v1",
                as_of_date=now,
            )
            session.add(rb)
            created += 1

        session.commit()

        return created


if __name__ == "__main__":
    created = build_rent_benchmarks()
    print(f"Built {created} rent benchmark buckets.")
