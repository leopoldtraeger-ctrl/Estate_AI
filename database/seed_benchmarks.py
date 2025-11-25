# database/seed_benchmarks.py

from datetime import datetime
from sqlalchemy import select

from database.models import (
    ConstructionCostBenchmark,
    RenovationModule,
    RentBenchmark,
)


def seed_construction_costs(session):
    # schon was drin? -> nichts tun
    existing = session.scalar(
        select(ConstructionCostBenchmark.id).limit(1)
    )
    if existing:
        return

    rows = [
        ConstructionCostBenchmark(
            country="UK",
            region="London",
            building_type="residential",
            spec_level="basic",
            cost_per_sqm_min=1200,
            cost_per_sqm_max=1600,
            currency="GBP",
            source="Internal estimate",
            as_of_date=datetime(2024, 1, 1),
        ),
        ConstructionCostBenchmark(
            country="UK",
            region="London",
            building_type="residential",
            spec_level="standard",
            cost_per_sqm_min=1700,
            cost_per_sqm_max=2300,
            currency="GBP",
            source="Internal estimate",
            as_of_date=datetime(2024, 1, 1),
        ),
        ConstructionCostBenchmark(
            country="UK",
            region="London",
            building_type="residential",
            spec_level="premium",
            cost_per_sqm_min=2400,
            cost_per_sqm_max=3200,
            currency="GBP",
            source="Internal estimate",
            as_of_date=datetime(2024, 1, 1),
        ),
    ]
    session.add_all(rows)
    session.commit()


def seed_renovation_modules(session):
    existing = session.scalar(select(RenovationModule.id).limit(1))
    if existing:
        return

    rows = [
        RenovationModule(
            name="Küche komplett",
            description="Full kitchen refurbishment incl. cabinets, appliances, plumbing, electrics.",
            typical_cost_min=8000,
            typical_cost_max=15000,
            impact_on_rent_pct=5.0,
            lifetime_years=15,
        ),
        RenovationModule(
            name="Bad Kernsanierung",
            description="Full bathroom refurbishment incl. tiling, sanitary, plumbing.",
            typical_cost_min=6000,
            typical_cost_max=12000,
            impact_on_rent_pct=4.0,
            lifetime_years=15,
        ),
        RenovationModule(
            name="Fenster & Dämmung",
            description="New windows and basic external insulation.",
            typical_cost_min=10000,
            typical_cost_max=25000,
            impact_on_rent_pct=3.0,
            impact_on_energy_rating_classes=1.0,
            lifetime_years=25,
        ),
    ]
    session.add_all(rows)
    session.commit()


def seed_rent_benchmarks(session):
    existing = session.scalar(select(RentBenchmark.id).limit(1))
    if existing:
        return

    rows = [
        RentBenchmark(
            country="UK",
            city="London",
            submarket_id=None,        # kannst du später auf echte Submarket-IDs mappen
            bedrooms=1,
            property_type="Flat",
            rent_psqm_min=30,
            rent_psqm_max=45,
            currency="GBP",
            source="Internal rent benchmark",
            as_of_date=datetime(2024, 1, 1),
        ),
        RentBenchmark(
            country="UK",
            city="London",
            submarket_id=None,
            bedrooms=2,
            property_type="Flat",
            rent_psqm_min=28,
            rent_psqm_max=40,
            currency="GBP",
            source="Internal rent benchmark",
            as_of_date=datetime(2024, 1, 1),
        ),
        RentBenchmark(
            country="UK",
            city="London",
            submarket_id=None,
            bedrooms=3,
            property_type="House",
            rent_psqm_min=25,
            rent_psqm_max=38,
            currency="GBP",
            source="Internal rent benchmark",
            as_of_date=datetime(2024, 1, 1),
        ),
    ]
    session.add_all(rows)
    session.commit()


def seed_all_benchmarks(session):
    """
    Wird beim App-Start aufgerufen, fügt Daten nur ein, wenn Tabellen leer sind.
    """
    seed_construction_costs(session)
    seed_renovation_modules(session)
    seed_rent_benchmarks(session)
