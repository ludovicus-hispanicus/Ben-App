from typing import List

from pydantic import BaseModel
from pydantic.json import Union

from entities.dimensions import Dimensions


class ItemDto(BaseModel):
    symbol: str = ""
    letter: Union[str, None] = ""
    dimensions: Dimensions = None
    certainty: str = ""
    image_id: str = -1


class SubmitDto(BaseModel):
    text_id: int = 999999
    items: List[List[ItemDto]]
    akkademia: List[str] = []
    is_fixed: bool = False
