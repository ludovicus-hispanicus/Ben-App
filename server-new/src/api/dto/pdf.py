from typing import List

from pydantic import BaseModel

from entities.dimensions import Dimensions


class PostPdf(BaseModel):
    raw_pdf: bytes
    page: int
