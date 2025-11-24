class ScraperError(Exception):
    """Base class for scraper exceptions."""
    pass


class ExtractionError(ScraperError):
    """Raised when extraction fails."""
    pass


class NetworkError(ScraperError):
    """Raised when network or page loading fails."""
    pass
