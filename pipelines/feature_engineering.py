import re

def extract_price_number(price_str: str):
    if not price_str:
        return None
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else None

def add_features(data: dict) -> dict:
    numeric_price = extract_price_number(data.get("price"))

    return {
        **data,
        "price_numeric": numeric_price,
        "is_luxury": numeric_price and numeric_price > 5_000_000,
    }
