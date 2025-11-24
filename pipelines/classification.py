def classify_price_segment(price_numeric: int):
    if not price_numeric:
        return "unknown"
    if price_numeric < 500_000:
        return "low"
    if price_numeric < 2_000_000:
        return "mid"
    return "high"

def classify_listing(data: dict) -> dict:
    price_segment = classify_price_segment(data.get("price_numeric"))
    return {
        **data,
        "price_segment": price_segment,
    }
