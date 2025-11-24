import sqlite3
from textwrap import shorten


def main(limit: int = 10):
    # Verbindung zur SQLite-Datenbank
    conn = sqlite3.connect("estateai.db")
    cur = conn.cursor()

    # Ein paar Spalten aus listings holen
    cur.execute(
        """
        SELECT
            id,
            url,
            price,
            bedrooms,
            bathrooms,
            property_type,
            description
        FROM listings
        ORDER BY price DESC
        LIMIT ?;
        """,
        (limit,),
    )

    rows = cur.fetchall()

    if not rows:
        print("No listings found in the database.")
        conn.close()
        return

    print(f"\nShowing top {len(rows)} listings by price:\n")

    for row in rows:
        (
            listing_id,
            url,
            price,
            bedrooms,
            bathrooms,
            property_type,
            description,
        ) = row

        print("-" * 80)
        print(f"ID:          {listing_id}")
        print(f"URL:         {url}")
        print(f"Price (GBP): {price:,.0f}" if price is not None else "Price:       n/a")
        print(f"Bedrooms:    {bedrooms}")
        print(f"Bathrooms:   {bathrooms}")
        print(f"Type:        {property_type}")
        print("\nDescription:")
        short_desc = shorten((description or "").replace("\n", " "), width=300, placeholder="...")
        print(short_desc)
        print()

    conn.close()


if __name__ == "__main__":
    main(limit=10)
