from typing import List, Optional

from pydantic import BaseModel


class CreateDatasetDto(BaseModel):
    name: str
    parent_id: Optional[int] = None


class RenameDatasetDto(BaseModel):
    name: str


class MoveDatasetDto(BaseModel):
    parent_id: Optional[int] = None


class AssignTextDto(BaseModel):
    dataset_id: Optional[int] = None


class DatasetPreviewDto(BaseModel):
    dataset_id: int
    name: str
    created_at: int
    parent_id: Optional[int] = None
    text_count: int = 0
    curated_count: int = 0
    curated_lines: int = 0
    children_count: int = 0
    for_production: bool = False


class SetProductionDto(BaseModel):
    for_production: bool


class DatasetTreeNodeDto(BaseModel):
    dataset_id: int
    name: str
    parent_id: Optional[int] = None
    text_count: int = 0
    curated_count: int = 0
    children_count: int = 0
    children: List['DatasetTreeNodeDto'] = []


DatasetTreeNodeDto.update_forward_refs()
