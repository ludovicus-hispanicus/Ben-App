from typing import Optional

from entities.new_text import DbModel


class Project(DbModel):
    project_id: int
    name: str
    created_at: int = -1
    parent_id: Optional[int] = None
