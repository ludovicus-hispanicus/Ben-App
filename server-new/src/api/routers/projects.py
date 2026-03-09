import io
import json
import zipfile
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.dto.project import (
    CreateProjectDto, RenameProjectDto, MoveProjectDto, AssignTextDto,
    ProjectPreviewDto, ProjectTreeNodeDto
)
from api.dto.text import NewTextPreviewDto
from common.global_handlers import global_projects_handler, global_new_text_handler

router = APIRouter(
    prefix="/api/v1/projects",
    tags=["projects"],
    responses={404: {"description": "Not found"}}
)


def _compute_text_stats() -> dict:
    """Compute per-project text stats in a single pass over all texts.
    Returns {project_id: {count, curated_count, curated_lines}}.
    """
    all_texts = global_new_text_handler.list_texts(limit=0)
    stats: dict = {}
    for t in all_texts:
        pid = t.project_id
        if pid is None:
            continue
        if pid not in stats:
            stats[pid] = {"count": 0, "curated_count": 0, "curated_lines": 0}
        stats[pid]["count"] += 1
        if t.is_curated:
            stats[pid]["curated_count"] += 1
            stats[pid]["curated_lines"] += t.lines_count
    return stats


def _compute_children_counts() -> dict:
    """Compute children counts from all projects in a single pass.
    Returns {project_id: children_count}.
    """
    all_projects = global_projects_handler.list_projects(parent_id=None)
    counts: dict = {}
    for p in all_projects:
        if p.parent_id is not None:
            counts[p.parent_id] = counts.get(p.parent_id, 0) + 1
    return counts


def _build_project_previews(projects) -> list:
    """Build ProjectPreviewDto list using batch-loaded stats (2 queries total)."""
    text_stats = _compute_text_stats()
    children_counts = _compute_children_counts()
    result = []
    for p in projects:
        stats = text_stats.get(p.project_id, {"count": 0, "curated_count": 0, "curated_lines": 0})
        result.append(ProjectPreviewDto(
            project_id=p.project_id,
            name=p.name,
            created_at=p.created_at,
            parent_id=p.parent_id,
            text_count=stats["count"],
            curated_count=stats["curated_count"],
            curated_lines=stats["curated_lines"],
            children_count=children_counts.get(p.project_id, 0)
        ))
    return result


@router.get("/list")
async def list_projects(parent_id: Optional[int] = None) -> List[ProjectPreviewDto]:
    projects = global_projects_handler.list_projects(parent_id=parent_id)
    if not projects:
        return []
    return _build_project_previews(projects)


@router.get("/tree")
async def get_project_tree():
    """Get full project tree with nested children and text counts."""
    text_stats = _compute_text_stats()
    text_counts = {}
    for pid, stats in text_stats.items():
        text_counts[pid] = {
            "text_count": stats["count"],
            "curated_count": stats["curated_count"]
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


@router.patch("/texts/{text_id}/assign")
async def assign_text(text_id: int, dto: AssignTextDto):
    """Assign a text to a project, or unassign it (project_id=null)."""
    if dto.project_id is not None:
        project = global_projects_handler.get_project(dto.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Target project not found")
    global_new_text_handler.assign_text_to_project(text_id=text_id, project_id=dto.project_id)
    return {"updated": True}


@router.get("/texts/{text_id}/export")
async def export_single_text(text_id: int, format: str = "txt"):
    """Export a single text. Formats: txt, json, csv."""
    data = global_new_text_handler.export_single_text(text_id)
    if not data:
        raise HTTPException(status_code=404, detail="Text not found")
    label = data["label"] or "unlabeled"
    fname_base = f'{data["label"]}_{text_id}' if data["label"] else str(text_id)

    if format == "json":
        return Response(
            content=json.dumps(data, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname_base}.json"'}
        )
    elif format == "csv":
        import csv as csv_mod
        buf = io.StringIO()
        writer = csv_mod.writer(buf)
        writer.writerow(["label", "content", "text_id", "part", "identifier"])
        writer.writerow([data["label"], data["content"], data["text_id"], data["part"], data["identifier"]])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname_base}.csv"'}
        )
    else:  # txt
        header = f'=== {label} | text_id={data["text_id"]} | {data["identifier"]} ===\n'
        return Response(
            content=header + data["content"],
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname_base}.txt"'}
        )


@router.get("/{project_id}/export")
async def export_project(project_id: int, format: str = "json"):
    """Export all texts in a project. Formats: json, tsv, txt, zip_txt, zip_json."""
    project = global_projects_handler.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    texts = global_new_text_handler.export_project_texts(project_id)
    project_name = project.name.replace(" ", "_")

    if format == "json":
        content = json.dumps(texts, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{project_name}.json"'}
        )

    elif format == "tsv":
        lines = ["label\tcontent\ttext_id\tpart\tidentifier"]
        for t in texts:
            escaped_content = t["content"].replace("\t", " ").replace("\n", "\\n")
            lines.append(f'{t["label"]}\t{escaped_content}\t{t["text_id"]}\t{t["part"]}\t{t["identifier"]}')
        content = "\n".join(lines)
        return Response(
            content=content,
            media_type="text/tab-separated-values; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{project_name}.tsv"'}
        )

    elif format == "txt":
        blocks = []
        for t in texts:
            label = t["label"] or "unlabeled"
            blocks.append(f'=== {label} | text_id={t["text_id"]} | {t["identifier"]} ===\n{t["content"]}')
        content = "\n\n".join(blocks)
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{project_name}.txt"'}
        )

    elif format == "zip_txt":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for t in texts:
                fname = f'{t["label"]}_{t["text_id"]}.txt' if t["label"] else f'{t["text_id"]}.txt'
                label = t["label"] or "unlabeled"
                header = f'=== {label} | text_id={t["text_id"]} | {t["identifier"]} ===\n'
                zf.writestr(fname, header + t["content"])
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project_name}_txt.zip"'}
        )

    elif format == "zip_json":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for t in texts:
                fname = f'{t["label"]}_{t["text_id"]}.json' if t["label"] else f'{t["text_id"]}.json'
                zf.writestr(fname, json.dumps(t, ensure_ascii=False, indent=2))
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project_name}_json.zip"'}
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unknown format: {format}. Use json, tsv, txt, zip_txt, or zip_json.")


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
    if not children:
        return []
    return _build_project_previews(children)


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


@router.get("/unassigned/texts")
async def list_unassigned_texts() -> List[NewTextPreviewDto]:
    return global_new_text_handler.list_unassigned_texts()


@router.get("/{project_id}/texts")
async def list_project_texts(project_id: int) -> List[NewTextPreviewDto]:
    return global_new_text_handler.list_texts_by_project(project_id=project_id)
