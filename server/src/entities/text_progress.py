from typing import Optional, List

from pydantic import Field
from pydantic.main import BaseModel

from api.dto.letter import Letter
from api.dto.submit import ItemDto
from entities.common import PyObjectId
from entities.dimensions import Dimensions


class TextProgress(BaseModel):
    id: Optional[PyObjectId] = Field(alias='_id')
    items: List[List[ItemDto]]
    user_email: str
    akkademia: List[str] = []
    submit_time: str = None

    def to_transliterations(self) -> List[List[Letter]]:
        return [[Letter(letter=letter.letter, symbol=letter.symbol, certainty=letter.certainty) for letter in line]
                for line in self.items]

    def to_dimensions(self) -> List[List[Dimensions]]:
        return [[item.dimensions for item in line]
                for line in self.items]
