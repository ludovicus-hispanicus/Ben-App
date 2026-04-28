from typing import Optional

from entities.new_text import DbModel


class Dataset(DbModel):
    dataset_id: int
    name: str
    created_at: int = -1
    parent_id: Optional[int] = None
    for_production: bool = False  # opt-in: include this folder's texts in the production view
