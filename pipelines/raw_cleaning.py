def clean_text(value: str) -> str:
    if not value:
        return None
    return (
        value.replace("\n", " ")
        .replace("\t", " ")
        .replace("\r", "")
        .strip()
    )

def clean_listing(data: dict) -> dict:
    return {
        **data,
        "title": clean_text(data.get("title")),
        "price": clean_text(data.get("price")),
        "address": clean_text(data.get("address")),
        "description": clean_text(data.get("description")),
    }
