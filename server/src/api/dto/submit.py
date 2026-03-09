from typing import List, Union, Optional

from pydantic import BaseModel

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
