from typing import List

from pydantic import BaseModel

from entities.dimensions import Dimensions


class CuredResultDto(BaseModel):
    dimensions: List[Dimensions]
    lines: List[str] = None
