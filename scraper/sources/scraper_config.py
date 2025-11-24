# scraper/sources/scraper_config.py

SCRAPER_SETTINGS = {
    "TIMEOUT": 70000,
    "HEADLESS": True,
    "RETRY_ATTEMPTS": 3,
    "WAIT_BETWEEN_RETRIES": 2,
    "ENABLE_OCR": True,
    "VIEWPORT": {"width": 1600, "height": 1000},
    "LOCALE": "en-GB",
    "TIMEZONE": "Europe/London",
}
