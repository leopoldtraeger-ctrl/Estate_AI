CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    title TEXT,
    price TEXT,
    address TEXT,
    description TEXT,
    features TEXT,
    source TEXT,
    ocr_raw TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Pyramiden-Schema für EstateAI (SQLite Dialekt)

CREATE TABLE IF NOT EXISTS markets (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    country         TEXT NOT NULL DEFAULT 'UK',
    code            TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS submarkets (
    id                  INTEGER PRIMARY KEY,
    market_id           INTEGER NOT NULL,
    name                TEXT NOT NULL,
    postcode_prefix     TEXT,
    boundary_note       TEXT,
    data_quality_score  REAL DEFAULT 0.0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (market_id) REFERENCES markets (id)
);

CREATE TABLE IF NOT EXISTS properties (
    id                  INTEGER PRIMARY KEY,
    submarket_id        INTEGER,
    full_address        TEXT NOT NULL,
    postcode            TEXT,
    city                TEXT,
    latitude            REAL,
    longitude           REAL,
    property_type       TEXT,
    bedrooms            INTEGER,
    bathrooms           INTEGER,
    floor_area_sqm      REAL,
    year_built          INTEGER,
    is_new_build        INTEGER DEFAULT 0,
    data_quality_score  REAL DEFAULT 0.0,
    first_seen_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (submarket_id) REFERENCES submarkets (id)
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id              INTEGER PRIMARY KEY,
    portal          TEXT NOT NULL DEFAULT 'rightmove',
    location_query  TEXT,
    started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at     DATETIME,
    total_listings  INTEGER DEFAULT 0,
    success_count   INTEGER DEFAULT 0,
    error_count     INTEGER DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS listings (
    id              INTEGER PRIMARY KEY,
    property_id     INTEGER NOT NULL,
    scrape_run_id   INTEGER,
    portal          TEXT NOT NULL DEFAULT 'rightmove',
    external_id     TEXT,
    url             TEXT NOT NULL,
    listing_type    TEXT,
    status          TEXT,
    tenure          TEXT,
    price           REAL,
    currency        TEXT NOT NULL DEFAULT 'GBP',
    bedrooms        INTEGER,
    bathrooms       INTEGER,
    property_type   TEXT,
    scraped_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    first_seen_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    description     TEXT,
    FOREIGN KEY (property_id) REFERENCES properties (id),
    FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs (id)
);

CREATE TABLE IF NOT EXISTS raw_scrapes (
    id          INTEGER PRIMARY KEY,
    listing_id  INTEGER NOT NULL,
    scraped_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    raw_text    TEXT,
    raw_html    TEXT,
    raw_meta    TEXT,
    FOREIGN KEY (listing_id) REFERENCES listings (id)
);
