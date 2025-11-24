from pydantic import BaseModel

class Property(BaseModel):
    id: int
    title: str
    price: float
