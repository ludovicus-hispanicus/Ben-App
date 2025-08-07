from typing import List
from typing import Union

from pydantic.main import BaseModel

from api.dto.letter import Letter
from entities.dimensions import Dimensions


class StageOneDto(BaseModel):
    text_id: int
    dimensions: List[List[Union[Dimensions, None]]]
    transliteration: List[List[Letter]] = None
    akkademia: List[str] = None
    metadata: List[dict] = None
    is_fixed: bool = False
