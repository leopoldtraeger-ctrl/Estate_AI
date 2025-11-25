# services/__init__.py

from .analytics import (
    get_best_cost_benchmark,
    estimate_capex_for_property,
    compute_refurb_risk_scores,
)


class PropertyService:
    def get_property(self, id: int):
        return {"id": id}
