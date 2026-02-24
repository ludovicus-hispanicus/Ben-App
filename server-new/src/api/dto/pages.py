"""DTOs for the Document Library / Pages API."""
from typing import List, Optional
from pydantic import BaseModel


class PageInfo(BaseModel):
    """A single page/image within a project."""
    filename: str
    page_number: int
    thumbnail_url: str
    full_url: str


class ProjectInfo(BaseModel):
    """A project (folder) in the library."""
    project_id: str
    name: str
    image_count: int
    created_at: str
    parent_id: Optional[str] = None
    children_count: int = 0


class ProjectTreeNode(BaseModel):
    """A project node in the tree with nested children."""
    project_id: str
    name: str
    image_count: int = 0
    created_at: str = ""
    parent_id: Optional[str] = None
    children_count: int = 0
    total_image_count: int = 0
    children: List['ProjectTreeNode'] = []


ProjectTreeNode.update_forward_refs()


class ProjectDetail(BaseModel):
    """Project with its pages."""
    project_id: str
    name: str
    pages: List[PageInfo]
    total_pages: int


class ProjectListResponse(BaseModel):
    """List of all projects."""
    projects: List[ProjectInfo]


class CreateProjectDto(BaseModel):
    name: str
    parent_id: Optional[str] = None


class RenameProjectDto(BaseModel):
    name: str


class MoveProjectDto(BaseModel):
    parent_id: Optional[str] = None


class UploadResponse(BaseModel):
    """Response after uploading files to a project."""
    project_id: str
    name: str
    page_count: int
    message: str
