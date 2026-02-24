from typing import List, Optional

from fastapi import APIRouter, HTTPException

from api.dto.project import (
    CreateProjectDto, RenameProjectDto, MoveProjectDto,
    ProjectPreviewDto, ProjectTreeNodeDto
)
from api.dto.text import NewTextPreviewDto
from common.global_handlers import global_projects_handler, global_new_text_handler

router = APIRouter(
    prefix="/api/v1/projects",
    tags=["projects"],
    responses={404: {"description": "Not found"}}
)


@router.get("/list")
async def list_projects(parent_id: Optional[int] = None) -> List[ProjectPreviewDto]:
    projects = global_projects_handler.list_projects(parent_id=parent_id)
    result = []
    for p in projects:
        texts = global_new_text_handler.list_texts_by_project(p.project_id)
        curated_count = sum(1 for t in texts if t.is_curated)
        children_count = global_projects_handler.count_children(p.project_id)
        result.append(ProjectPreviewDto(
            project_id=p.project_id,
            name=p.name,
            created_at=p.created_at,
            parent_id=p.parent_id,
            text_count=len(texts),
            curated_count=curated_count,
            children_count=children_count
        ))
    return result


@router.get("/tree")
async def get_project_tree():
    """Get full project tree with nested children and text counts."""
    all_projects = global_projects_handler.list_projects(parent_id=None)
    text_counts = {}
    for p in all_projects:
        texts = global_new_text_handler.list_texts_by_project(p.project_id)
        curated_count = sum(1 for t in texts if t.is_curated)
        text_counts[p.project_id] = {
            "text_count": len(texts),
            "curated_count": curated_count
        }
    return global_projects_handler.get_tree(text_counts=text_counts)


@router.post("/create")
async def create_project(dto: CreateProjectDto) -> int:
    try:
        return global_projects_handler.create_project(
            name=dto.name,
            parent_id=dto.parent_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{project_id}/rename")
async def rename_project(project_id: int, dto: RenameProjectDto):
    project = global_projects_handler.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    global_projects_handler.rename_project(project_id=project_id, name=dto.name)
    return {"updated": True}


@router.patch("/{project_id}/move")
async def move_project(project_id: int, dto: MoveProjectDto):
    """Move a project to a new parent folder."""
    project = global_projects_handler.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    result = global_projects_handler.move_project(project_id=project_id, new_parent_id=dto.parent_id)
    if not result.get("updated"):
        raise HTTPException(status_code=400, detail=result.get("error", "Move failed"))
    return result


@router.delete("/{project_id}")
async def delete_project(project_id: int):
    project = global_projects_handler.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Check if folder has children
    result = global_projects_handler.delete_project(project_id=project_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
    # Unassign texts from this project (they become unassigned, not deleted)
    global_new_text_handler.unassign_texts_from_project(project_id)
    return result


@router.get("/{project_id}/children")
async def get_children(project_id: int) -> List[ProjectPreviewDto]:
    """Get direct children of a project."""
    project = global_projects_handler.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    children = global_projects_handler.get_children(project_id)
    result = []
    for p in children:
        texts = global_new_text_handler.list_texts_by_project(p.project_id)
        curated_count = sum(1 for t in texts if t.is_curated)
        children_count = global_projects_handler.count_children(p.project_id)
        result.append(ProjectPreviewDto(
            project_id=p.project_id,
            name=p.name,
            created_at=p.created_at,
            parent_id=p.parent_id,
            text_count=len(texts),
            curated_count=curated_count,
            children_count=children_count
        ))
    return result


@router.get("/{project_id}/breadcrumb")
async def get_breadcrumb(project_id: int) -> List[ProjectPreviewDto]:
    """Get the path from root to this project."""
    breadcrumb = global_projects_handler.get_breadcrumb(project_id)
    if not breadcrumb:
        raise HTTPException(status_code=404, detail="Project not found")
    return [
        ProjectPreviewDto(
            project_id=p.project_id,
            name=p.name,
            created_at=p.created_at,
            parent_id=p.parent_id,
        )
        for p in breadcrumb
    ]


@router.get("/{project_id}/texts")
async def list_project_texts(project_id: int) -> List[NewTextPreviewDto]:
    return global_new_text_handler.list_texts_by_project(project_id=project_id)


@router.get("/unassigned/texts")
async def list_unassigned_texts() -> List[NewTextPreviewDto]:
    return global_new_text_handler.list_unassigned_texts()
