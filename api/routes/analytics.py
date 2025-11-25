# api/routes/analytics.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database.connection import get_session
from database.models import Property
from services import analytics as analytics_service


router = APIRouter(prefix="/analytics", tags=["analytics"])


class CapexRequest(BaseModel):
    property_id: int
    country: str = "UK"
    region: str = "London"
    building_type: str = "residential"
    spec_level: str = "standard"
    renovation_module_ids: Optional[List[int]] = None
    target_rent_pcm: Optional[float] = None
    current_rent_pcm: Optional[float] = None
    opex_per_year: Optional[float] = None
    purchase_price: Optional[float] = None


@router.post("/capex")
def capex_endpoint(payload: CapexRequest, db=Depends(get_session)):
    try:
        result = analytics_service.estimate_capex_for_property(
            db=db,
            property_id=payload.property_id,
            country=payload.country,
            region=payload.region,
            building_type=payload.building_type,
            spec_level=payload.spec_level,
            renovation_module_ids=payload.renovation_module_ids,
            target_rent_pcm=payload.target_rent_pcm,
            current_rent_pcm=payload.current_rent_pcm,
            opex_per_year=payload.opex_per_year,
            purchase_price=payload.purchase_price,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/refurb/{property_id}")
def refurb_scores(property_id: int, db=Depends(get_session)):
    prop = db.query(Property).get(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    scores = analytics_service.compute_refurb_risk_scores(prop)
    db.commit()
    return scores
