import asyncio
import io
import json
import zipfile
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.dto.dataset import (
    CreateDatasetDto, RenameDatasetDto, MoveDatasetDto, AssignTextDto,
    DatasetPreviewDto, DatasetTreeNodeDto, SetProductionDto
)
from api.dto.text import NewTextPreviewDto
from common.global_handlers import global_datasets_handler, global_new_text_handler

router = APIRouter(
    prefix="/api/v1/datasets",
    tags=["datasets"],
    responses={404: {"description": "Not found"}}
)


def _compute_text_stats() -> dict:
    """Compute per-dataset text stats using the lightweight shard-level counter.
    Returns {dataset_id: {count, curated_count, curated_lines}}.
    """
    return global_new_text_handler.get_stats_per_dataset()


def _compute_children_counts() -> dict:
    """Compute children counts from all datasets in a single pass.
    Returns {dataset_id: children_count}.
    """
    all_datasets = global_datasets_handler.list_datasets(parent_id=None)
    counts: dict = {}
    for d in all_datasets:
        if d.parent_id is not None:
            counts[d.parent_id] = counts.get(d.parent_id, 0) + 1
    return counts


def _build_dataset_previews(datasets) -> list:
    """Build DatasetPreviewDto list using batch-loaded stats (2 queries total)."""
    text_stats = _compute_text_stats()
    children_counts = _compute_children_counts()
    result = []
    for d in datasets:
        stats = text_stats.get(d.dataset_id, {"count": 0, "curated_count": 0, "curated_lines": 0})
        result.append(DatasetPreviewDto(
            dataset_id=d.dataset_id,
            name=d.name,
            created_at=d.created_at,
            parent_id=d.parent_id,
            text_count=stats["count"],
            curated_count=stats["curated_count"],
            curated_lines=stats["curated_lines"],
            children_count=children_counts.get(d.dataset_id, 0),
            for_production=getattr(d, 'for_production', False)
        ))
    return result


def _enrich_ahw_columns(texts: list):
    """Compute column (a/b) for merged AHw entries on the fly from YOLO annotations.

    Parses each text's identifier to find the YOLO dataset, page, and order,
    then applies the column-aware sort (headers first, left column top→bottom,
    right column top→bottom) to determine which column each entry belongs to.

    Temporary helper — can be removed once all dictionaries use the
    snippets-only workflow where column is already in the manifest.
    """
    import os
    import re
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)
    _storage_path = os.environ.get("STORAGE_PATH", "data")
    datasets_path = Path(os.environ.get(
        "YOLO_DATA_PATH", os.path.join(_storage_path, "yolo")
    )).resolve() / "datasets"

    if not datasets_path.exists():
        return

    HEADER_CLASSES = {"guidewords", "pageNumber", "pagenumber"}

    def _is_header(class_name: str) -> bool:
        return class_name in HEADER_CLASSES or class_name.lower().replace("_", "").replace(" ", "") in HEADER_CLASSES

    def _ann_sort_key(rec):
        if _is_header(rec["class_name"]):
            return (0, rec["x_center"])
        col = 0 if rec["x_center"] < 0.5 else 1
        return (1, col, rec["y_center"])

    # Cache: (dataset_name, page_stem) → list of sorted annotations with column
    _page_cache: dict = {}

    def _load_page_anns(dataset_name: str, page_stem: str, class_names: dict):
        cache_key = (dataset_name, page_stem)
        if cache_key in _page_cache:
            return _page_cache[cache_key]

        result = []
        dataset_path = datasets_path / dataset_name
        for split in ["train", "val"]:
            img_dir = dataset_path / "images" / split
            label_dir = dataset_path / "labels" / split
            label_file = label_dir / f"{page_stem}.txt"
            if not label_file.exists():
                continue
            anns = []
            with open(label_file, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        anns.append({
                            "class_id": int(parts[0]),
                            "class_name": class_names.get(int(parts[0]), f"class_{parts[0]}"),
                            "x_center": float(parts[1]),
                            "y_center": float(parts[2]),
                        })
            # Column-aware sort
            anns.sort(key=_ann_sort_key)
            for i, a in enumerate(anns):
                a["order"] = i
                a["column"] = "a" if a["x_center"] < 0.5 else "b"
            result = anns
            break

        _page_cache[cache_key] = result
        return result

    # Cache: dataset_name → class_names dict
    _class_cache: dict = {}

    def _get_class_names(dataset_name: str) -> dict:
        if dataset_name in _class_cache:
            return _class_cache[dataset_name]
        meta_path = datasets_path / dataset_name / "metadata.json"
        class_names = {}
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                for c in meta.get("classes", []):
                    class_names[c["id"]] = c["name"]
            except Exception:
                pass
        _class_cache[dataset_name] = class_names
        return class_names

    # Find matching YOLO dataset for a given identifier prefix
    _ds_lookup: dict = {}

    def _find_dataset(ds_prefix: str) -> str:
        if ds_prefix in _ds_lookup:
            return _ds_lookup[ds_prefix]
        # ds_prefix is like "ahw_a_auto_test", dataset dir is "AHw_A_auto_test"
        for d in datasets_path.iterdir():
            if d.is_dir() and d.name.lower() == ds_prefix.lower():
                _ds_lookup[ds_prefix] = d.name
                return d.name
        # Try with case-insensitive partial match
        for d in datasets_path.iterdir():
            if d.is_dir() and d.name.lower().replace("-", "_") == ds_prefix.lower().replace("-", "_"):
                _ds_lookup[ds_prefix] = d.name
                return d.name
        _ds_lookup[ds_prefix] = ""
        return ""

    # Parse identifier and compute column
    # Identifier format: "A/ahw_a_auto_test-0001-012-mainEntry.png"
    # or cross-page: "A/ahw_a_auto_test-0001-012-p0002-mainEntry.png"
    ident_pattern = re.compile(
        r'^(?P<prefix>.+?)-(?P<page>\d{4})-(?P<order>\d{3})(?:-(?:p\d{4}|\d{3}))*-(?P<class>\w+)\.png$'
    )

    for t in texts:
        ident = t.get("identifier", "")
        if "/" not in ident:
            continue
        _, filename = ident.split("/", 1)

        m = ident_pattern.match(filename)
        if not m:
            continue

        ds_prefix = m.group("prefix")
        page_num = m.group("page")
        order = int(m.group("order"))

        dataset_name = _find_dataset(ds_prefix)
        if not dataset_name:
            continue

        class_names = _get_class_names(dataset_name)
        page_stem = f"page_{page_num}"
        page_anns = _load_page_anns(dataset_name, page_stem, class_names)

        if not page_anns:
            continue

        # Find entry at the given order (0-indexed, matching merge numbering)
        # For cross-page entries, use the first page's column
        if order < len(page_anns):
            t["column"] = page_anns[order]["column"]
        elif page_anns:
            # Order exceeds annotations — use last known
            t["column"] = page_anns[-1]["column"]


def _list_datasets_sync(parent_id: Optional[int]) -> List[DatasetPreviewDto]:
    datasets = global_datasets_handler.list_datasets(parent_id=parent_id)
    if not datasets:
        return []
    return _build_dataset_previews(datasets)


@router.get("/list")
async def list_datasets(parent_id: Optional[int] = None) -> List[DatasetPreviewDto]:
    return await asyncio.to_thread(_list_datasets_sync, parent_id)


def _get_dataset_tree_sync():
    text_stats = _compute_text_stats()
    text_counts = {}
    for did, stats in text_stats.items():
        text_counts[did] = {
            "text_count": stats["count"],
            "curated_count": stats["curated_count"]
        }
    return global_datasets_handler.get_tree(text_counts=text_counts)


@router.get("/tree")
async def get_dataset_tree():
    """Get full dataset tree with nested children and text counts."""
    return await asyncio.to_thread(_get_dataset_tree_sync)


@router.post("/create")
async def create_dataset(dto: CreateDatasetDto) -> int:
    try:
        return global_datasets_handler.create_dataset(
            name=dto.name,
            parent_id=dto.parent_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/texts/{text_id}/assign")
async def assign_text(text_id: int, dto: AssignTextDto):
    """Assign a text to a dataset, or unassign it (dataset_id=null)."""
    if dto.dataset_id is not None:
        dataset = global_datasets_handler.get_dataset(dto.dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="Target dataset not found")
    global_new_text_handler.assign_text_to_dataset(text_id=text_id, dataset_id=dto.dataset_id)
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


@router.get("/{dataset_id}/export")
async def export_dataset(dataset_id: int, format: str = "json"):
    """Export all texts in a dataset. Formats: json, tsv, txt, zip_txt, zip_json."""
    dataset = global_datasets_handler.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    texts = global_new_text_handler.export_dataset_texts(dataset_id)
    dataset_name = dataset.name.replace(" ", "_")

    if format == "json":
        content = json.dumps(texts, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{dataset_name}.json"'}
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
            headers={"Content-Disposition": f'attachment; filename="{dataset_name}.tsv"'}
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
            headers={"Content-Disposition": f'attachment; filename="{dataset_name}.txt"'}
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
            headers={"Content-Disposition": f'attachment; filename="{dataset_name}_txt.zip"'}
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
            headers={"Content-Disposition": f'attachment; filename="{dataset_name}_json.zip"'}
        )

    elif format == "ahw_json":
        # Temporary format: enrich merged AHw entries with column info
        # computed on the fly from YOLO annotations using column-aware sort.
        # Can be deprecated once all dictionaries use the snippets-only workflow.
        _enrich_ahw_columns(texts)
        content = json.dumps(texts, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{dataset_name}.json"'}
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unknown format: {format}. Use json, tsv, txt, zip_txt, zip_json, or ahw_json.")


@router.patch("/{dataset_id}/rename")
async def rename_dataset(dataset_id: int, dto: RenameDatasetDto):
    dataset = global_datasets_handler.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    global_datasets_handler.rename_dataset(dataset_id=dataset_id, name=dto.name)
    return {"updated": True}


@router.patch("/{dataset_id}/production")
async def set_dataset_production(dataset_id: int, dto: SetProductionDto):
    """Flag (or unflag) a dataset for production. Only flagged datasets' texts appear in /production/grouped."""
    dataset = global_datasets_handler.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    global_datasets_handler.set_for_production(dataset_id=dataset_id, for_production=dto.for_production)
    return {"updated": True, "for_production": dto.for_production}


@router.patch("/{dataset_id}/move")
async def move_dataset(dataset_id: int, dto: MoveDatasetDto):
    """Move a dataset to a new parent folder."""
    dataset = global_datasets_handler.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    result = global_datasets_handler.move_dataset(dataset_id=dataset_id, new_parent_id=dto.parent_id)
    if not result.get("updated"):
        raise HTTPException(status_code=400, detail=result.get("error", "Move failed"))
    return result


def _delete_dataset_sync(dataset_id: int):
    dataset = global_datasets_handler.get_dataset(dataset_id)
    if not dataset:
        return {"not_found": True}
    result = global_datasets_handler.delete_dataset(dataset_id=dataset_id)
    if not result.get("deleted"):
        return result
    global_new_text_handler.unassign_texts_from_dataset(dataset_id)
    return result


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: int):
    result = await asyncio.to_thread(_delete_dataset_sync, dataset_id)
    if result.get("not_found"):
        raise HTTPException(status_code=404, detail="Dataset not found")
    if not result.get("deleted"):
        raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
    return result


@router.get("/{dataset_id}/children")
async def get_children(dataset_id: int) -> List[DatasetPreviewDto]:
    """Get direct children of a dataset."""
    dataset = global_datasets_handler.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    children = global_datasets_handler.get_children(dataset_id)
    if not children:
        return []
    return _build_dataset_previews(children)


@router.get("/{dataset_id}/breadcrumb")
async def get_breadcrumb(dataset_id: int) -> List[DatasetPreviewDto]:
    """Get the path from root to this dataset."""
    breadcrumb = global_datasets_handler.get_breadcrumb(dataset_id)
    if not breadcrumb:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return [
        DatasetPreviewDto(
            dataset_id=d.dataset_id,
            name=d.name,
            created_at=d.created_at,
            parent_id=d.parent_id,
        )
        for d in breadcrumb
    ]


@router.get("/unassigned/texts")
async def list_unassigned_texts() -> List[NewTextPreviewDto]:
    return global_new_text_handler.list_unassigned_texts()


@router.get("/{dataset_id}/texts")
async def list_dataset_texts(dataset_id: int, skip: int = 0, limit: int = 500):
    texts = global_new_text_handler.list_texts_by_dataset(dataset_id=dataset_id, skip=skip, limit=limit)
    total = global_new_text_handler.get_dataset_text_count(dataset_id=dataset_id)
    return {"items": texts, "total": total, "skip": skip, "limit": limit}
