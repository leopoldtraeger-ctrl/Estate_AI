"""
EstateAI Config Module
----------------------
Zentrale Konfiguration für das gesamte EstateAI-System.

Beinhaltet:
- Pfad-Management
- Umgebungsvariablen
- Scraper-Settings
- API-Settings
- Logging-Konfiguration
- Auto-Verzeichnisgenerierung
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# -----------------------------
# Load .env if available
# -----------------------------
load_dotenv()

# -----------------------------
# Base project paths
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Create folders if missing
def ensure_dirs():
    dirs = [
        PROJECT_ROOT / "scraper/debug",
        PROJECT_ROOT / "logs",
        PROJECT_ROOT / "database",
        PROJECT_ROOT / "app",
        PROJECT_ROOT / "api",
        PROJECT_ROOT / "pipelines",
        PROJECT_ROOT / "airflow",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

ensure_dirs()

# -----------------------------
# Scraper configuration
# -----------------------------
SCRAPER = {
    "BASE_URL": "https://www.rightmove.co.uk",
    "TIMEOUT": 60000,
    "VIEWPORT": {"width": 1600, "height": 1000},
    "HEADLESS": True,
    "RETRIES": 3,
    "ENABLE_OCR_FALLBACK": True,
}

# -----------------------------
# Database configuration
# -----------------------------
DATABASE = {
    "DB_PATH": str(PROJECT_ROOT / "database" / "estateai.db"),
    "ECHO_SQL": False,
}

# -----------------------------
# Logging configuration
# -----------------------------
LOGGING = {
    "LOG_DIR": str(PROJECT_ROOT / "logs"),
    "LOG_FILE": str(PROJECT_ROOT / "logs" / "estateai.log"),
    "LEVEL": os.getenv("LOG_LEVEL", "INFO"),
}

# -----------------------------
# API configuration
# -----------------------------
API = {
    "HOST": "0.0.0.0",
    "PORT": 8000,
    "RELOAD": True,
    "TITLE": "EstateAI API",
    "DESCRIPTION": "Enterprise-grade Real Estate AI Backend",
}

# -----------------------------
# Airflow configuration
# -----------------------------
AIRFLOW = {
    "SCRAPE_DAG_ID": "estateai_scraper_daily",
    "PIPELINE_DAG_ID": "estateai_full_pipeline",
    "SCHEDULE": "@daily",
}

# -----------------------------
# ML / Feature Settings
# -----------------------------
ML = {
    "EMBEDDINGS_ENABLED": False,
    "FEATURE_FLAGS": {
        "USE_ADVANCED_EPC_MODEL": False,
        "USE_LLAMA_SUMMARY": False,
    }
}

# -----------------------------
# Config classes
# -----------------------------
class Config:
    DEBUG = False
    TESTING = False
    SCRAPER = SCRAPER
    DATABASE = DATABASE
    LOGGING = LOGGING
    API = API
    AIRFLOW = AIRFLOW
    ML = ML


class DevConfig(Config):
    DEBUG = True
    SCRAPER = {**SCRAPER, "HEADLESS": False}
    LOGGING = {**LOGGING, "LEVEL": "DEBUG"}


class ProdConfig(Config):
    DEBUG = False
    SCRAPER = {**SCRAPER, "HEADLESS": True}
    LOGGING = {**LOGGING, "LEVEL": "INFO"}


# active config
ACTIVE_CONFIG = ProdConfig() if os.getenv("ENV") == "prod" else DevConfig()
