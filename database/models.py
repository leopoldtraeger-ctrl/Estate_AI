"""
Pyramidenförmiges Datenmodell für EstateAI.

Ebene 1: Market (z.B. London)
Ebene 2: Submarket (z.B. Holland Park / W11)
Ebene 3: Property (physische Immobilie)
Ebene 4: Listing (konkrete Portal-Anzeige, zeitlich veränderlich)
Ebene 5: RawScrape (Rohdaten & Text)
Ebene 6: ScrapeRun (Meta pro Run)
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import relationship, declarative_base

# WICHTIG: Base kommt NICHT mehr aus connection.py,
# sondern wird hier direkt definiert.
Base = declarative_base()


# --------------------------------------
# 1. MARKETS (z.B. "London")
# --------------------------------------
class Market(Base):
    __tablename__ = "markets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)             # "London"
    country = Column(String(50), nullable=False, default="UK")
    code = Column(String(20), nullable=True)               # "LON" o.ä.

    created_at = Column(DateTime, default=datetime.utcnow)

    submarkets = relationship("Submarket", back_populates="market")

    def __repr__(self):
        return f"<Market id={self.id} name={self.name!r}>"


# --------------------------------------
# 2. SUBMARKETS (z.B. "Holland Park / W11")
# --------------------------------------
class Submarket(Base):
    __tablename__ = "submarkets"

    id = Column(Integer, primary_key=True, index=True)
    market_id = Column(Integer, ForeignKey("markets.id"), nullable=False)

    name = Column(String(150), nullable=False)              # "Holland Park"
    postcode_prefix = Column(String(20), nullable=True)     # "W11"
    boundary_note = Column(Text, nullable=True)             # Freitext-Beschreibung

    data_quality_score = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)

    market = relationship("Market", back_populates="submarkets")
    properties = relationship("Property", back_populates="submarket")

    def __repr__(self):
        return f"<Submarket id={self.id} name={self.name!r}>"


# --------------------------------------
# 3. PROPERTIES (physische Immobilie)
# --------------------------------------
class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    submarket_id = Column(Integer, ForeignKey("submarkets.id"), nullable=True)

    full_address = Column(String(300), nullable=False)
    postcode = Column(String(20), nullable=True)
    city = Column(String(100), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    property_type = Column(String(50), nullable=True)       # "House", "Flat", "Penthouse"
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    floor_area_sqm = Column(Float, nullable=True)
    year_built = Column(Integer, nullable=True)
    is_new_build = Column(Boolean, default=False)

    # 🏗️ Construction / Refurb
    last_renovation_year = Column(Integer, nullable=True)
    energy_rating = Column(String(10), nullable=True)           # z.B. "A", "B", "C"
    refurb_intensity = Column(String(16), nullable=True)        # 'none', 'light', 'medium', 'full'
    capex_estimate_per_sqm = Column(Float, nullable=True)
    energy_risk_score = Column(Float, nullable=True)            # 0–100
    opex_estimate_per_year = Column(Float, nullable=True)
    current_rent_pcm = Column(Float, nullable=True)

    data_quality_score = Column(Float, default=0.0)

    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)

    submarket = relationship("Submarket", back_populates="properties")
    listings = relationship(
        "Listing",
        back_populates="property",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Property id={self.id} address={self.full_address!r}>"


# --------------------------------------
# 4. LISTINGS (konkrete Portal-Anzeigen)
# --------------------------------------
class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    scrape_run_id = Column(Integer, ForeignKey("scrape_runs.id"), nullable=True)

    portal = Column(String(50), nullable=False, default="rightmove")
    external_id = Column(String(50), nullable=True)          # z.B. "161075213"
    url = Column(String(500), nullable=False)

    listing_type = Column(String(20), nullable=True)         # "sale", "rent"
    status = Column(String(20), nullable=True)               # "active", "sold", "under_offer"
    tenure = Column(String(50), nullable=True)               # "Freehold", "Leasehold"

    price = Column(Float, nullable=True)                     # 27500000.0
    currency = Column(String(10), nullable=False, default="GBP")

    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    property_type = Column(String(50), nullable=True)

    scraped_at = Column(DateTime, default=datetime.utcnow)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)

    description = Column(Text, nullable=True)

    property = relationship("Property", back_populates="listings")
    scrape_run = relationship("ScrapeRun", back_populates="listings")
    raw_scrapes = relationship(
        "RawScrape",
        back_populates="listing",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Listing id={self.id} portal={self.portal} url={self.url!r}>"


# --------------------------------------
# 5. RAW_SCRAPES (Rohdaten & Debug)
# --------------------------------------
class RawScrape(Base):
    __tablename__ = "raw_scrapes"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)

    scraped_at = Column(DateTime, default=datetime.utcnow)

    raw_text = Column(Text, nullable=True)   # Volltext (z.B. body_text)
    raw_html = Column(Text, nullable=True)   # optional: HTML, wenn du willst
    raw_meta = Column(Text, nullable=True)   # optional: JSON-String mit Meta

    listing = relationship("Listing", back_populates="raw_scrapes")

    def __repr__(self):
        return f"<RawScrape id={self.id} listing_id={self.listing_id}>"


# --------------------------------------
# 6. SCRAPE_RUNS (Meta je Scraper-Lauf)
# --------------------------------------
class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id = Column(Integer, primary_key=True, index=True)

    portal = Column(String(50), nullable=False, default="rightmove")
    location_query = Column(String(200), nullable=True)  # z.B. "London, pages=3"

    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    total_listings = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)

    status = Column(String(20), nullable=False, default="running")  # running/success/failed

    listings = relationship("Listing", back_populates="scrape_run")

    def __repr__(self):
        return f"<ScrapeRun id={self.id} portal={self.portal} status={self.status}>"


# --------------------------------------
# 7. Construction / Renovation Stammdaten
# --------------------------------------
class ConstructionCostBenchmark(Base):
    __tablename__ = "construction_cost_benchmarks"

    id = Column(Integer, primary_key=True)
    country = Column(String(64), index=True)                  # z.B. "UK"
    region = Column(String(128), index=True)                  # "London", "Manchester"
    building_type = Column(String(64))                        # "residential", "office"
    spec_level = Column(String(32))                           # "basic", "standard", "premium"

    cost_per_sqm_min = Column(Float)
    cost_per_sqm_max = Column(Float)

    currency = Column(String(8), default="GBP")
    source = Column(String(256), nullable=True)
    as_of_date = Column(DateTime, nullable=True)

    def __repr__(self):
        return (
            f"<ConstructionCostBenchmark id={self.id} "
            f"{self.country}/{self.region} {self.building_type} {self.spec_level}>"
        )


class RenovationModule(Base):
    __tablename__ = "renovation_modules"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True)              # "Küche komplett", "Bad Kernsanierung"
    description = Column(String(512), nullable=True)

    typical_cost_min = Column(Float)
    typical_cost_max = Column(Float)

    impact_on_rent_pct = Column(Float, nullable=True)    # z.B. 5 = +5%
    impact_on_energy_rating_classes = Column(Float, nullable=True)  # z.B. 1.0 = +1 Klasse

    lifetime_years = Column(Integer, nullable=True)      # technische/ökonomische Lebensdauer

    def __repr__(self):
        return f"<RenovationModule id={self.id} name={self.name!r}>"


class ConstructionIndex(Base):
    __tablename__ = "construction_indices"

    id = Column(Integer, primary_key=True)
    index_name = Column(String(128))                     # "UK Residential Construction Cost Index"
    region = Column(String(128), nullable=True)
    value = Column(Float)                                # Indexstand (relativ)
    base_year = Column(Integer, nullable=True)
    date = Column(DateTime, index=True)

    def __repr__(self):
        return f"<ConstructionIndex id={self.id} name={self.index_name!r} date={self.date}>"
