from pydantic.main import BaseModel

from api.dto.index import Index


class Dimensions(BaseModel):
    x: float
    y: float
    height: float
    width: float
    index: Index = None
