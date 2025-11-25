# services/analytics.py
from typing import List, Optional

from sqlalchemy.orm import Session

from database.models import (
    Property,
    ConstructionCostBenchmark,
    RenovationModule,
)


def get_best_cost_benchmark(
    db: Session,
    country: str,
    region: str,
    building_type: str,
    spec_level: str,
) -> Optional[ConstructionCostBenchmark]:
    """
    Holt den passendsten ConstructionCostBenchmark für Land/Region/Typ/Standard.
    """
    q = (
        db.query(ConstructionCostBenchmark)
        .filter(
            ConstructionCostBenchmark.country == country,
            ConstructionCostBenchmark.building_type == building_type,
            ConstructionCostBenchmark.spec_level == spec_level,
        )
        .order_by(
            (ConstructionCostBenchmark.region == region).desc(),
            ConstructionCostBenchmark.as_of_date.desc().nullslast(),
        )
    )
    return q.first()


def estimate_capex_for_property(
    db: Session,
    property_id: int,
    country: str = "UK",
    region: str = "London",
    building_type: str = "residential",
    spec_level: str = "standard",
    renovation_module_ids: Optional[List[int]] = None,
    target_rent_pcm: Optional[float] = None,
    current_rent_pcm: Optional[float] = None,
    opex_per_year: Optional[float] = None,
    purchase_price: Optional[float] = None,
):
    """
    Schätzt Capex für ein Property + optional neue Rendite nach Refurb.
    """
    prop = db.query(Property).get(property_id)
    if not prop:
        raise ValueError("Property not found")

    if not prop.floor_area_sqm:
        raise ValueError("Property has no floor_area_sqm")

    bm = get_best_cost_benchmark(
        db=db,
        country=country,
        region=region,
        building_type=building_type,
        spec_level=spec_level,
    )
    if not bm:
        raise ValueError("No construction cost benchmark found")

    # Basis-Capex
    base_cost_per_sqm = (bm.cost_per_sqm_min + bm.cost_per_sqm_max) / 2.0
    base_capex = base_cost_per_sqm * prop.floor_area_sqm

    # Renovation Modules
    modules = []
    modules_capex = 0.0
    impact_rent_pct = 0.0

    if renovation_module_ids:
        modules = (
            db.query(RenovationModule)
            .filter(RenovationModule.id.in_(renovation_module_ids))
            .all()
        )
        for m in modules:
            cost_avg = (m.typical_cost_min + m.typical_cost_max) / 2.0
            modules_capex += cost_avg
            if m.impact_on_rent_pct:
                impact_rent_pct += m.impact_on_rent_pct

    total_capex = base_capex + modules_capex
    capex_per_sqm = total_capex / prop.floor_area_sqm

    # Miete
    if current_rent_pcm is None:
        current_rent_pcm = prop.current_rent_pcm
    if current_rent_pcm is not None:
        new_rent_pcm = current_rent_pcm * (1 + impact_rent_pct / 100.0)
    elif target_rent_pcm is not None:
        new_rent_pcm = target_rent_pcm
    else:
        new_rent_pcm = None

    # Opex
    if opex_per_year is None:
        opex_per_year = prop.opex_estimate_per_year or 0.0

    # Kaufpreis (am besten explizit per Payload)
    if purchase_price is None:
        purchase_price = None

    yearly_rent = new_rent_pcm * 12.0 if new_rent_pcm else None
    if yearly_rent is not None and purchase_price:
        new_yield = (yearly_rent - opex_per_year) / (purchase_price + total_capex)
    else:
        new_yield = None

    # optional speichern
    prop.capex_estimate_per_sqm = capex_per_sqm
    db.commit()

    return {
        "property_id": property_id,
        "base_capex": base_capex,
        "modules_capex": modules_capex,
        "total_capex": total_capex,
        "capex_per_sqm": capex_per_sqm,
        "modules": [m.name for m in modules],
        "impact_rent_pct": impact_rent_pct,
        "current_rent_pcm": current_rent_pcm,
        "new_rent_pcm": new_rent_pcm,
        "yearly_rent": yearly_rent,
        "new_yield": new_yield,
    }


def compute_refurb_risk_scores(prop: Property) -> dict:
    """
    Sehr einfache Heuristik für Refurb-Intensity + Energy-Risk.
    """
    refurb = "none"
    if prop.year_built:
        if prop.year_built < 1950:
            refurb = "full"
        elif prop.year_built < 1970:
            refurb = "medium"
        elif prop.year_built < 1990:
            refurb = "light"

    rating = (prop.energy_rating or "").upper().strip()
    rating_map = {
        "A": 10,
        "B": 20,
        "C": 40,
        "D": 60,
        "E": 75,
        "F": 90,
        "G": 100,
    }
    if rating in rating_map:
        score = rating_map[rating]
    else:
        score = 50.0

    prop.refurb_intensity = refurb
    prop.energy_risk_score = score

    return {
        "refurb_intensity": refurb,
        "energy_risk_score": score,
    }
