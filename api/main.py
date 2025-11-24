from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# IMPORT from your new listings scraper
from scraper.sources.rightmove_listings import (
    fetch_links_sync,
    scrape_property_sync,
    scrape_all_sync
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "EstateAI API running"}

# 1️⃣ Einzelne Immobilie
@app.get("/scrape/property")
def scrape_property(url: str):
    return scrape_property_sync(url)

# 2️⃣ Nur Links
@app.get("/scrape/listings")
def scrape_listings(location: str = "London", pages: int = 1):
    return {
        "location": location,
        "pages": pages,
        "links": fetch_links_sync(location, pages)
    }

# 3️⃣ Alle Listings + voll auslesen
@app.get("/scrape/all")
def scrape_all(location: str = "London", pages: int = 1):
    return scrape_all_sync(location, pages)
