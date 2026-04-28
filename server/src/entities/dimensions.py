from typing import Optional
from pydantic import BaseModel

from api.dto.index import Index


class Dimensions(BaseModel):
    x: float
    y: float
    height: float
    width: float
    index: Optional[Index] = None
    view_code: Optional[str] = None
