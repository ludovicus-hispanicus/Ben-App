"""
Pages Router - Project-based document library with folder hierarchy.

Endpoints:
  POST   /api/v1/pages/upload                                - Upload PDF or image (creates new project)
  POST   /api/v1/pages/projects                               - Create empty project (optionally inside parent)
  GET    /api/v1/pages/projects                               - List all projects
  GET    /api/v1/pages/tree                                    - Get full project tree (nested)
  GET    /api/v1/pages/projects/{project_id}                  - Get project detail with pages
  GET    /api/v1/pages/projects/{project_id}/children         - Get direct children of a project
  GET    /api/v1/pages/projects/{project_id}/breadcrumb       - Path from root to this project
  PATCH  /api/v1/pages/projects/{project_id}/rename           - Rename project
  PATCH  /api/v1/pages/projects/{project_id}/move             - Move project to new parent
  POST   /api/v1/pages/projects/{project_id}/upload           - Upload file to existing project
  GET    /api/v1/pages/projects/{project_id}/image/{page}     - Full-res page image
  GET    /api/v1/pages/projects/{project_id}/thumbnail/{page} - Page thumbnail
  DELETE /api/v1/pages/projects/{project_id}                  - Delete project
  DELETE /api/v1/pages/projects/{project_id}/pages             - Delete specific pages
"""
import logging
import os
from typing import List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from api.dto.pages import (ProjectListResponse, ProjectDetail, UploadResponse,
                           CreateProjectDto, RenameProjectDto, MoveProjectDto)
from handlers.pages_handler import PagesHandler

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/pages",
    tags=["pages"]
)

handler = PagesHandler()

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}
ALLOWED_PDF_TYPES = {"application/pdf", "application\\pdf"}


def _process_upload(file_bytes: bytes, filename: str, content_type: str,
                    project_id: str = None, project_name: str = None) -> UploadResponse:
    """Shared logic for upload endpoints."""
    if content_type in ALLOWED_PDF_TYPES or filename.lower().endswith(".pdf"):
        return handler.upload_pdf(file_bytes, filename, project_id=project_id, project_name=project_name)
    elif content_type in ALLOWED_IMAGE_TYPES or filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return handler.upload_image(file_bytes, filename, project_id=project_id, project_name=project_name)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type}. Upload PDF, PNG, or JPEG files."
        )


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...), name: str = Form(None)):
    """Upload a PDF (all pages extracted) or a single image. Creates a new project."""
    content_type = file.content_type or ""
    file_bytes = await file.read()
    return _process_upload(file_bytes, file.filename or "document.pdf", content_type, project_name=name)


@router.post("/projects", response_model=UploadResponse)
async def create_project(dto: CreateProjectDto):
    """Create a new empty project, optionally inside a parent folder."""
    try:
        return handler.create_project(dto.name, parent_id=dto.parent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects():
    """List all projects in the library."""
    return handler.list_projects()


@router.get("/tree")
async def get_project_tree():
    """Get full project tree with nested children."""
    return handler.get_tree()


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: str):
    """Get project detail with all its pages."""
    project = handler.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return project


@router.get("/projects/{project_id}/children")
async def get_children(project_id: str):
    """Get direct children of a project."""
    return handler.get_children(project_id)


@router.get("/projects/{project_id}/breadcrumb")
async def get_breadcrumb(project_id: str):
    """Get path from root to this project."""
    return handler.get_breadcrumb(project_id)


@router.patch("/projects/{project_id}/rename")
async def rename_project(project_id: str, dto: RenameProjectDto):
    """Rename a project."""
    success = handler.rename_project(project_id, dto.name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return {"updated": True}


@router.patch("/projects/{project_id}/move")
async def move_project(project_id: str, dto: MoveProjectDto):
    """Move a project to a new parent. parent_id=null moves to root."""
    result = handler.move_project(project_id, dto.parent_id)
    if not result.get("updated"):
        raise HTTPException(status_code=400, detail=result.get("error", "Move failed"))
    return result


@router.post("/projects/{project_id}/upload", response_model=UploadResponse)
async def upload_to_project(project_id: str, file: UploadFile = File(...)):
    """Upload a PDF or image to an existing project."""
    content_type = file.content_type or ""
    file_bytes = await file.read()
    try:
        return _process_upload(file_bytes, file.filename or "document.pdf", content_type, project_id=project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/projects/{project_id}/image/{page_number}")
async def get_page_image(project_id: str, page_number: int):
    """Get full-resolution page image."""
    page_path = handler.get_page_path(project_id, page_number)
    if not page_path or not os.path.exists(page_path):
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(page_path, media_type="image/png")


@router.get("/projects/{project_id}/thumbnail/{page_number}")
async def get_page_thumbnail(project_id: str, page_number: int):
    """Get page thumbnail JPEG."""
    thumb_path = handler.get_thumbnail_path(project_id, page_number)
    if thumb_path and os.path.exists(thumb_path):
        return FileResponse(thumb_path, media_type="image/jpeg")

    # Fallback to full image
    page_path = handler.get_page_path(project_id, page_number)
    if page_path and os.path.exists(page_path):
        return FileResponse(page_path, media_type="image/png")

    raise HTTPException(status_code=404, detail="Page not found")


@router.get("/projects/{project_id}/download")
async def download_project(project_id: str):
    """Download a project as a ZIP, recursively including child sub-folders."""
    try:
        zip_path = handler.download_project_zip(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

    project = handler.get_project(project_id)
    filename = f"{project.name}.zip" if project else f"{project_id}.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: os.unlink(zip_path)),
    )


@router.delete("/projects/{project_id}/pages")
async def delete_pages(project_id: str, page_numbers: List[int] = Body(..., embed=True)):
    """Delete specific pages from a project."""
    try:
        deleted = handler.delete_pages(project_id, page_numbers)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return {"deleted": deleted, "message": f"Deleted {deleted} page(s)"}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project and all its files. Refuses if project has subfolders."""
    result = handler.delete_project(project_id)
    if not result.get("deleted"):
        error = result.get("error", "Delete failed")
        status = 404 if "not found" in error.lower() else 400
        raise HTTPException(status_code=status, detail=error)
    return {"message": f"Project '{project_id}' deleted"}
