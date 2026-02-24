from typing import List, Optional

from pydantic import BaseModel


class CreateProjectDto(BaseModel):
    name: str
    parent_id: Optional[int] = None


class RenameProjectDto(BaseModel):
    name: str


class MoveProjectDto(BaseModel):
    parent_id: Optional[int] = None


class ProjectPreviewDto(BaseModel):
    project_id: int
    name: str
    created_at: int
    parent_id: Optional[int] = None
    text_count: int = 0
    curated_count: int = 0
    children_count: int = 0


class ProjectTreeNodeDto(BaseModel):
    project_id: int
    name: str
    parent_id: Optional[int] = None
    text_count: int = 0
    curated_count: int = 0
    children_count: int = 0
    children: List['ProjectTreeNodeDto'] = []


ProjectTreeNodeDto.update_forward_refs()
