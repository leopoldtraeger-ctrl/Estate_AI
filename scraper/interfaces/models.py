from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ScraperResult:
    url: str
    title: Optional[str]
    price: Optional[str]
    address: Optional[str]
    description: Optional[str]
    features: List[str]
    source: str
    ocr_raw: Optional[str] = None
