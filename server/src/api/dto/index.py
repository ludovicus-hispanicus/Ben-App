from pydantic import BaseModel


class Index(BaseModel):
    row: int
    col: int
