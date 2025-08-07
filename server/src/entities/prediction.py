from pydantic.main import BaseModel

from api.dto.letter import Letter
from entities.dimensions import Dimensions


class Prediction(BaseModel):
    letter: Letter
    dimensions: Dimensions
    image_id: int = -1





