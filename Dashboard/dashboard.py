import os
import sys
import math
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

import streamlit as st
from sqlalchemy import select, func
from dotenv import load_dotenv

import requests
from bs4 import BeautifulSoup
import html

# =========================
# Projekt-Root & .env laden
# =========================

BASE_DIR = Path(__file__).resolve().parents[1]  # eine Ebene über /Dashboard
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

# .env aus dem Projektroot laden (lokal)
load_dotenv(BASE_DIR / ".env")

from database.connection import get_session
from database import models
from database.models import Base  # für DB-Init
from database.ingest import ingest_bulk_results
from scraper.sources.rightmove_scraper import scrape_all_sync

# =========================
# OpenAI-Client für Chat
# =========================

try:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    openai_client = OpenAI(api_key=api_key)
except Exception as e:
    openai_client = None
    print("OpenAI client not available:", e)


# =========================
# DB-Init Helper
# =========================

def ensure_db_initialized() -> None:
    """
    Legt alle Tabellen an, falls sie noch nicht existieren.
    Wichtig für Streamlit Cloud, wo die DB frisch ist.
    """
    try:
        with get_session() as session:
            bind = session.get_bind()
            Base.metadata.create_all(bind=bind)
    except Exception as e:
        print("DB init failed (ignored):", e)


# =========================
# Helper: DB-Access
# =========================

def load_summary() -> Dict[str, Any]:
    with get_session() as session:
        total_listings = session.scalar(select(func.count(models.Listing.id)))
        max_price = session.scalar(select(func.max(models.Listing.price)))
        avg_price = session.scalar(select(func.avg(models.Listing.price)))
        avg_beds = session.scalar(select(func.avg(models.Listing.bedrooms)))

        return {
            "total_listings": total_listings or 0,
            "max_price": max_price or 0,
            "avg_price": avg_price or 0,
            "avg_beds": avg_beds or 0,
        }


def load_distinct_property_types() -> List[str]:
    with get_session() as session:
        stmt = select(models.Listing.property_type).distinct()
        rows = session.execute(stmt).all()
    types = sorted({r[0] for r in rows if r[0]})
    return types


def load_listings(
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_beds: Optional[int] = None,
    prop_type: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    with get_session() as session:
        stmt = (
            select(
                models.Listing.id,
                models.Listing.url,
                models.Listing.price,
                models.Listing.bedrooms,
                models.Listing.bathrooms,
                models.Listing.property_type,
                models.Listing.description,
            )
            .order_by(models.Listing.price.desc())
            .limit(limit)
        )

        if min_price is not None:
            stmt = stmt.where(models.Listing.price >= min_price)
        if max_price is not None:
            stmt = stmt.where(models.Listing.price <= max_price)
        if min_beds is not None:
            stmt = stmt.where(models.Listing.bedrooms >= min_beds)
        if prop_type and prop_type != "All":
            stmt = stmt.where(models.Listing.property_type == prop_type)

        rows = session.execute(stmt).all()

    data: List[Dict[str, Any]] = []
    for r in rows:
        desc = (r.description or "").replace("\n", " ")
        short_desc = (desc[:200] + "...") if len(desc) > 200 else desc

        data.append(
            {
                "id": r.id,
                "url": r.url,
                "price": r.price,
                "bedrooms": r.bedrooms,
                "bathrooms": r.bathrooms,
                "type": r.property_type,
                "description": short_desc,
                "description_full": desc,
            }
        )
    return data


def load_listing_by_id(listing_id: int) -> Optional[Dict[str, Any]]:
    """
    Holt ein einzelnes Listing nach ID aus der DB.
    """
    with get_session() as session:
        stmt = select(
            models.Listing.id,
            models.Listing.url,
            models.Listing.price,
            models.Listing.bedrooms,
            models.Listing.bathrooms,
            models.Listing.property_type,
            models.Listing.description,
        ).where(models.Listing.id == listing_id)

        row = session.execute(stmt).one_or_none()

    if row is None:
        return None

    desc = (row.description or "").replace("\n", " ")
    short_desc = (desc[:200] + "...") if len(desc) > 200 else desc

    return {
        "id": row.id,
        "url": row.url,
        "price": row.price,
        "bedrooms": row.bedrooms,
        "bathrooms": row.bathrooms,
        "type": row.property_type,
        "description": short_desc,
        "description_full": desc,
    }


def extract_property_ids_from_question(question: str) -> List[int]:
    """
    Versucht IDs aus der Frage zu ziehen, z.B.:
    - "Listing 5"
    - "ID 12"
    - "listing #7"
    """
    matches = re.findall(r"(?:id|listing|#)\s*(\d+)", question, flags=re.IGNORECASE)

    ids: List[int] = []
    for m in matches:
        try:
            ids.append(int(m))
        except ValueError:
            continue

    # Dedupe, Reihenfolge behalten
    return list(dict.fromkeys(ids))


# =========================
# Scraper + Ingest
# =========================

def refresh_data(location: str = "London", pages: int = 1):
    """
    Läuft deinen Scraper + Ingest einmal durch,
    um neue Rightmove-Daten zu holen.
    """
    ensure_db_initialized()

    # In der Cloud wird Playwright evtl. nicht laufen – Fehler dann im Log.
    results = scrape_all_sync(location=location, pages=pages)

    total, success, error = ingest_bulk_results(
        results,
        portal="rightmove",
        location_query=f"{location}, pages={pages}",
        listing_type="sale",
    )
    return total, success, error


# =========================
# Bilder von Rightmove holen
# =========================

@st.cache_data(show_spinner=False)
def get_listing_images(url: str) -> List[str]:
    """
    Versucht, eine Liste von Vorschaubildern von der Rightmove-Seite zu holen.
    Sucht zuerst in Meta-Tags, dann in <img>-Tags und gibt mehrere URLs zurück.
    """
    try:
        clean_url = url.split("#")[0]

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        resp = requests.get(clean_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        urls: List[str] = []

        # 1) Meta-Tags (og:image, secure_url, twitter:image)
        meta_candidates = [
            ("meta", {"property": "og:image"}),
            ("meta", {"property": "og:image:secure_url"}),
            ("meta", {"name": "twitter:image"}),
        ]
        for name, attrs in meta_candidates:
            tag = soup.find(name, attrs=attrs)
            if tag and tag.get("content"):
                urls.append(tag["content"])

        # 2) Rightmove-spezifische Gallery-/Hero-Bilder
        for img in soup.find_all("img", attrs={"data-testid": ["gallery-image", "hero-image"]}):
            for attr in ["src", "data-src", "data-lazy-src"]:
                src = img.get(attr)
                if src:
                    urls.append(src)

        # 3) Fallback: alle "vernünftigen" Bilder einsammeln
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if not src:
                continue
            if ("rightmove" in src or "media" in src) and src.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            ):
                urls.append(src)

        # Dedupe, Reihenfolge behalten
        deduped = list(dict.fromkeys(urls))
        return deduped

    except Exception:
        return []


# =========================
# Chat-Kontext bauen
# =========================

def build_chat_context(max_listings: int = 30) -> str:
    """
    Baut einen kompakten Text-Kontext aus der Datenbank:
    - Aggregierte Kennzahlen
    - Einige Beispiel-Listings
    """
    summary = load_summary()
    listings = load_listings(limit=max_listings)

    lines: List[str] = []

    lines.append(
        "High-level database summary:\n"
        f"- Total listings in DB: {summary['total_listings']}\n"
        f"- Max price: £{summary['max_price']:,.0f}\n"
        f"- Average price: £{summary['avg_price']:,.0f}\n"
        f"- Average bedrooms: {summary['avg_beds']:.2f}\n"
    )

    if not listings:
        lines.append("\nNo individual listings available yet.")
        return "\n".join(lines)

    lines.append("\nSample listings (id, price, bedrooms, bathrooms, type):")
    for l in listings[:max_listings]:
        lines.append(
            f"- id={l['id']}, price={l['price']}, "
            f"bedrooms={l['bedrooms']}, bathrooms={l['bathrooms']}, "
            f"type={l['type']}"
        )

    return "\n".join(lines)


def build_chat_context_for_question(question: str, max_listings: int = 30) -> str:
    """
    Kombiniert:
    - globale DB-Summary
    - Sample-Listings
    - explizite Details zu Listings, die in der Frage erwähnt wurden
    """
    base_context = build_chat_context(max_listings=max_listings)
    focus_ids = extract_property_ids_from_question(question)

    lines = [base_context]

    if focus_ids:
        lines.append("\n\nFocus listings mentioned in the question (full details where available):")
        for lid in focus_ids:
            listing = load_listing_by_id(lid)
            if listing:
                price = listing["price"]
                price_str = f"£{price:,.0f}" if price is not None and not math.isnan(price) else "n/a"

                lines.append(
                    f"- id={listing['id']}, price={price_str}, "
                    f"bedrooms={listing['bedrooms']}, bathrooms={listing['bathrooms']}, "
                    f"type={listing['type']}, url={listing['url']}"
                )
            else:
                lines.append(f"- id={lid} (not found in DB)")

    # Intent-Hints für das Modell
    q_lower = question.lower()
    intent_hints: List[str] = []
    if any(w in q_lower for w in ["rendite", "yield", "cap rate", "miete", "rental"]):
        intent_hints.append(
            "- The user is asking about rental yield / cap rate or income-based valuation. "
            "You should compute yields where possible and show the formula."
        )
    if any(w in q_lower for w in ["teuer", "billig", "expensive", "cheap", "overpriced", "underpriced"]):
        intent_hints.append(
            "- The user is asking whether a listing is expensive or cheap compared to the rest of the database. "
            "Compare the price level (and price per bedroom if useful) to averages in the context."
        )

    if intent_hints:
        lines.append("\n\nIntent hints for you as the model:")
        lines.extend(intent_hints)

    return "\n".join(lines)


def ask_chat_model(question: str, context: str) -> str:
    """
    Fragt das OpenAI-Modell. Falls kein Client vorhanden ist,
    gib eine freundliche Fehlermeldung zurück.
    """
    if openai_client is None:
        return (
            "The AI assistant is not configured yet (missing OpenAI client or API key).\n"
            "Please set OPENAI_API_KEY (e.g. in Streamlit Secrets) and make sure the "
            "'openai' package is installed."
        )

    system_content = (
        "You are EstateAI, a real estate & finance analyst working with a snapshot of "
        "Rightmove listings stored in a database.\n\n"
        "CRITICAL RULES:\n"
        "1) You may ONLY use numeric facts that appear in the provided database context. "
        "   Never invent concrete prices, rents, yields, or addresses.\n"
        "2) If important numeric inputs are missing (e.g. purchase price, expected rent, "
        "   specific listing ID, number of bedrooms), do NOT guess. Instead:\n"
        "   - Explain briefly which data is missing.\n"
        "   - Ask up to TWO very concrete follow-up questions to get that data.\n"
        "   - Do NOT output fake numbers just to give a complete answer.\n"
        "3) Answer in the same language as the user's question (German or English).\n\n"
        "OUTPUT STRUCTURE (unless the user explicitly asks for a different format):\n"
        "1. Short answer (1–3 sentences).\n"
        "2. Key numbers (bullet points with concrete figures from the context; include formulas "
        "   if you compute yields or ratios).\n"
        "3. Interpretation & investor view (how attractive is this, what is upside/downside, "
        "   how does it compare to other listings in the context).\n\n"
        "YIELD / RENTAL QUESTIONS:\n"
        "- When the user mentions a target yield (e.g. 4.5%), compute the implied annual and "
        "  monthly rent if the purchase price is known.\n"
        "- Clearly show the formula you use.\n"
        "- Compare the result qualitatively to the rest of the portfolio where possible.\n\n"
        "COMPARISON QUESTIONS (e.g. 'Is this expensive?'):\n"
        "- Compare the listing's price to averages in the context (overall and for similar "
        "  bedroom counts if possible).\n"
        "- Talk in relative terms (+/- %, above/below average) when the context allows it.\n"
    )

    messages = [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": (
                f"Database context (Rightmove scrape):\n{context}\n\n"
                f"User question:\n{question}"
            ),
        },
    ]

    completion = openai_client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0.15,
        messages=messages,
    )
    return completion.choices[0].message.content.strip()


# =========================
# Streamlit Tabs
# =========================

def render_listings_tab():
    # --- Data Controls: Refresh-Button ---
    with st.expander("Data controls (Scraper)", expanded=True):
        col_r1, col_r2 = st.columns([1, 3])

        if col_r1.button("🔄 Fetch latest data from Rightmove"):
            status_box = st.empty()
            status_box.info("Step 1/3: Starting Rightmove scraper (Playwright)…")

            with st.spinner("Scraping & ingesting latest Rightmove data…"):
                try:
                    total, success, error = refresh_data(location="London", pages=1)
                    status_box.success("Step 3/3: Done. Database updated with latest listings ✅")
                    st.success(f"Scrape run finished: total={total}, success={success}, error={error}")
                except Exception as e:
                    status_box.error(f"Error while scraping: {e}")
                    st.error(f"Scraper error: {e}")

        st.caption(
            "Der Button triggert den Rightmove-Scraper (Playwright) und schreibt die Ergebnisse in die estateai.db."
        )

    st.markdown("---")

    # --- Summary KPIs ---
    summary = load_summary()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Listings", summary["total_listings"])
    col2.metric("Max Price (GBP)", f"{summary['max_price']:,.0f}")
    col3.metric("Avg Price (GBP)", f"{summary['avg_price']:,.0f}")
    col4.metric("Avg Bedrooms", f"{summary['avg_beds']:.2f}")

    st.markdown("---")

    # --- Filter ---
    st.subheader("🔍 Filter")

    prop_types = ["All"] + load_distinct_property_types()

    col_f1, col_f2, col_f3, col_f4 = st.columns(4)

    min_price = col_f1.number_input("Min Price (GBP)", value=0.0, step=1_000_000.0)
    max_price = col_f2.number_input("Max Price (GBP)", value=100_000_000.0, step=1_000_000.0)
    min_beds = col_f3.number_input("Min Bedrooms", value=0, step=1)
    prop_type = col_f4.selectbox("Property Type", options=prop_types)

    st.markdown("---")

    # --- Listings-Table ---
    listings = load_listings(
        min_price=min_price or None,
        max_price=max_price or None,
        min_beds=min_beds or None,
        prop_type=prop_type,
        limit=200,
    )

    st.subheader(f"📄 Listings (Treffer: {len(listings)})")

    if not listings:
        st.info("Keine Listings gefunden – eventuell Filter anpassen oder Scraper laufen lassen.")
        return

    table_data = [
        {
            "ID": l["id"],
            "Price (GBP)": l["price"],
            "Bedrooms": l["bedrooms"],
            "Bathrooms": l["bathrooms"],
            "Type": l["type"],
            "URL": l["url"],
            "Description": l["description"],
        }
        for l in listings
    ]
    st.dataframe(table_data, use_container_width=True)

    # --- Detail-View ---
    st.markdown("### 🔎 Listing Details")

    col_left, col_right = st.columns([1, 2])

    with col_left:
        ids = [l["id"] for l in listings]
        selected_id = st.selectbox("Listing ID auswählen", ids)
        selected = next(l for l in listings if l["id"] == selected_id)

        st.write(f"**URL:** [{selected['url']}]({selected['url']})")
        if selected["price"] is not None and not math.isnan(selected["price"]):
            st.write(f"**Price:** £{selected['price']:,.0f}")
        else:
            st.write("**Price:** n/a")
        st.write(f"**Bedrooms:** {selected['bedrooms']}")
        st.write(f"**Bathrooms:** {selected['bathrooms']}")
        st.write(f"**Type:** {selected['type']}")

    with col_right:
        # Bilder – einfacher "Carousel"-Viewer mit Pfeilen
        image_urls = get_listing_images(selected["url"])

        if image_urls:
            state_key = f"img_idx_{selected['id']}"

            if state_key not in st.session_state:
                st.session_state[state_key] = 0

            nav_left, nav_center, nav_right = st.columns([1, 4, 1])
            with nav_left:
                prev_clicked = st.button("◀", key=f"prev_{selected['id']}_prev")
            with nav_right:
                next_clicked = st.button("▶", key=f"next_{selected['id']}_next")

            if prev_clicked:
                st.session_state[state_key] = (st.session_state[state_key] - 1) % len(image_urls)
            if next_clicked:
                st.session_state[state_key] = (st.session_state[state_key] + 1) % len(image_urls)

            current_idx = st.session_state[state_key]
            current_img = image_urls[current_idx]

            st.image(current_img, use_container_width=True)
            st.caption(f"Image {current_idx + 1} of {len(image_urls)} (Rightmove)")
        else:
            st.info("No image preview available for this listing.")

        # Beschreibung
        st.write("**Full Description:**")
        st.write(selected["description_full"])


def render_chat_tab():
    st.subheader("💬 EstateAI – AI Assistant")

    st.markdown(
        "Stell Fragen zu den aktuell in der Datenbank gespeicherten Immobilien.\n\n"
        "- Beispiele: *„Wie ist die durchschnittliche Anzahl Zimmer?“*, "
        "*„Wie verteilen sich die Preise?“*, "
        "*„Ist Listing 5 im Vergleich zu den anderen teuer?“*, "
        "*„Wie hoch wäre die Brutto-Mietrendite bei 4,5 % Rendite-Annahme?“*"
    )

    # Warnung, falls keine Listings vorhanden
    summary_for_chat = load_summary()
    if summary_for_chat["total_listings"] == 0:
        st.warning(
            "Aktuell sind noch keine Listings in der Datenbank. "
            "Bitte zuerst im Tab **Listings** den Scraper laufen lassen."
        )
        return

    if openai_client is None:
        st.warning(
            "OPENAI_API_KEY ist nicht gesetzt oder der Client konnte nicht initialisiert werden.\n"
            "Bitte den API Key in den Streamlit Secrets oder der .env-Datei hinterlegen."
        )

    # Chat-History initialisieren
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []

    # Chat zurücksetzen
    reset_col, _ = st.columns([1, 5])
    with reset_col:
        if st.button("🧹 Chat zurücksetzen"):
            st.session_state["chat_messages"] = []
            st.rerun()

    # -------- Chatfenster mit Scroll --------
    messages_html = ""
    for msg in st.session_state["chat_messages"]:
        role_label = "You" if msg["role"] == "user" else "EstateAI"
        align = "flex-end" if msg["role"] == "user" else "flex-start"
        bg = "#1f2937" if msg["role"] == "user" else "#020617"

        safe_content = html.escape(msg["content"])

        # WICHTIG: keine führenden Leerzeichen, sonst macht Markdown einen Codeblock
        messages_html += f"""
<div style="display:flex; justify-content:{align}; margin-bottom:0.35rem;">
  <div style="max-width:80%;">
    <div style="font-size:0.7rem; opacity:0.7; margin-bottom:0.15rem;">
      {role_label}
    </div>
    <div style="
        background:{bg};
        padding:0.5rem 0.75rem;
        border-radius:0.75rem;
        white-space:pre-wrap;
        font-size:0.9rem;
        line-height:1.3;
    ">
      {safe_content}
    </div>
  </div>
</div>
"""

    st.markdown(
        f"""
<div style="
    height: 420px;
    overflow-y: auto;
    border-radius: 0.75rem;
    border: 1px solid #334155;
    padding: 0.75rem;
    background-color: #020617;
    margin-bottom: 0.5rem;
">
    {messages_html}
</div>
""",
        unsafe_allow_html=True,
    )

    # -------- Eingabefeld --------
    prompt = st.chat_input("Ask a question about these listings…")

    if prompt:
        st.session_state["chat_messages"].append({"role": "user", "content": prompt})

        with st.spinner("Analyzing the current portfolio and database context…"):
            context = build_chat_context_for_question(prompt)
            answer = ask_chat_model(prompt, context)

        st.session_state["chat_messages"].append({"role": "assistant", "content": answer})

        st.rerun()


# =========================
# Haupt-Entry
# =========================

def main():
    # Tabellen anlegen, falls sie fehlen (wichtig in der Cloud)
    ensure_db_initialized()

    st.set_page_config(
        page_title="EstateAI – Investor Dashboard",
        layout="wide",
    )

    st.title("🏡 EstateAI – Investor Dashboard (Rightmove MVP)")

    st.markdown(
        "Dieses Dashboard zeigt echte Rightmove-Daten, "
        "gescraped mit unserem Playwright-Scraper und in einer strukturierten Datenbank gespeichert."
    )

    tab_listings, tab_chat = st.tabs(["Listings", "AI Assistant"])

    with tab_listings:
        render_listings_tab()

    with tab_chat:
        render_chat_tab()


if __name__ == "__main__":
    main()
