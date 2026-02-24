from typing import Dict, List

from pydantic import BaseModel

from api.dto.index import Index


class Letter(BaseModel):
    letter: str = None
    symbol: str = None
    certainty: str = ""
    index: Index = None


class AIGuess(BaseModel):
    letter: Letter
    all_letters: str
    probability: float
    index: Index = None



