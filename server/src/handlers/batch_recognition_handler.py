"""
Batch Recognition Handler - Processes multiple images through OCR and auto-saves results.
Follows the YOLO auto-annotate pattern for async job management.
"""

import asyncio
import base64
import logging
import math
import os
import shutil
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PIL import Image

from api.dto.submissions import TextIdentifiersDto, TransliterationSubmitDto
from clients.anthropic_client import AnthropicCancelledError
from clients.gemini_client import GeminiCancelledError, GeminiRateLimitError
from clients.ocr_factory import OCRFactory
from entities.dimensions import Dimensions
from common.global_handlers import global_new_text_handler
from entities.new_text import TransliterationSource
from handlers.pages_handler import PagesHandler
from mongo.mongo_client import MongoClient
from utils.storage_utils import StorageUtils

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

# ── Dynamic batching: size categories ──
# Classification uses pixel AREA (width × height) to account for wide images.
# (name, min_area, max_area, batch_size)
# max_area=None means unbounded
SIZE_CATEGORIES = [
    ("xxs",  0,         15_000,     20),   # tiny snippets: pageNumber, guideWord (~60×90)
    ("xs",   15_000,    100_000,    15),   # small snippets: refEntry, discussion (~400×80)
    ("s",    100_000,   500_000,    5),    # e.g. ≤ ~707×707
    ("m",    500_000,   1_500_000,  2),    # e.g. ≤ ~1225×1225
    ("l",    1_500_000, 4_000_000,  1),    # e.g. ≤ ~2000×2000
    ("xl",   4_000_000, 10_000_000, 1),    # e.g. ≤ ~3162×3162
    ("xxl",  10_000_000, 25_000_000, 1),   # e.g. ≤ ~5000×5000
    ("xxxl", 25_000_000, None,      1),    # very large images
]

TILE_TARGET_HEIGHT = 2500  # px — target height for each tile when splitting tall images
TILE_OVERLAP = 100         # px — overlap between tiles to avoid cutting text mid-line
TILE_MERGE_MARKER = "************************"  # inserted at tile merge points for manual review

# Structural markers that VLMs emit from prompt instructions —
# if these are the ONLY content, the OCR effectively returned nothing.
import re
# Match marker tokens anywhere in a line (not just at start) so that a single
# line containing both column markers (e.g. "# COLUMN A # COLUMN B") is
# correctly identified as having no real content, while a line that begins
# with a marker but continues with real text (e.g. "# COLUMN A *ma-ri*...")
# is correctly identified as having content.
_STRUCTURAL_TOKEN_RE = re.compile(
    r"#\s*COLUMN\s*[A-Z]\b|"
    + re.escape(TILE_MERGE_MARKER),
    re.IGNORECASE,
)
_VOLUME_TITLE_RE = re.compile(
    r"^\s*THE\s+ASSYRIAN\s+DICTIONARY\b.*$",
    re.IGNORECASE,
)


def _has_real_content(lines: list[str]) -> bool:
    """Return True if *lines* contains at least one line with actual content
    (i.e. anything beyond column headers, tile-merge markers, or volume titles)."""
    for line in lines or []:
        if _VOLUME_TITLE_RE.match(line.strip()):
            continue
        if _STRUCTURAL_TOKEN_RE.sub("", line).strip():
            return True
    return False


def _classify_image(height: int, width: int = 0) -> Tuple[str, int]:
    """Return (category_name, batch_size) for given pixel dimensions.
    Uses pixel area (width × height) for classification. If width is 0,
    estimates a square aspect ratio for backward compatibility.
    """
    area = height * width if width > 0 else height * height
    for name, lo, hi, bs in SIZE_CATEGORIES:
        if hi is None or area < hi:
            return name, bs
    return "xxxl", 1


def _detect_content_bbox(
    img: "Image.Image", pad_frac: float = 0.01
) -> Tuple[int, int, int, int]:
    """Detect the bounding box of the main body content in an image.
    Skips thin header/footer lines (e.g. watermarks, page numbers) that are
    separated from the body by a whitespace gap.
    Returns (left, top, right, bottom) with a small padding.
    Falls back to 2% margin crop if detection fails.
    """
    import numpy as np
    width, height = img.size
    fallback = (
        int(width * 0.02), int(height * 0.02),
        width - int(width * 0.02), height - int(height * 0.02),
    )
    try:
        gray = img.convert("L")
        arr = np.array(gray)
        # Threshold: pixels darker than 240 are "content"
        mask = arr < 240
        if not mask.any():
            return fallback

        # Per-row content density (fraction of dark pixels)
        row_density = mask.mean(axis=1)
        has_content = row_density > 0.001  # row has at least some ink

        # Find the main body by skipping isolated header/footer strips.
        # Scan from top: skip content rows until we hit a gap >= min_gap,
        # then the body starts at the next content row after that gap.
        min_gap = int(height * 0.02)  # gap must be at least 2% of height

        # --- Top: find body start ---
        body_top = 0
        in_content = False
        gap_start = None
        for y in range(height):
            if has_content[y]:
                if gap_start is not None and (y - gap_start) >= min_gap:
                    # Found a real gap — body starts here
                    body_top = y
                    break
                in_content = True
                gap_start = None
            else:
                if in_content and gap_start is None:
                    gap_start = y

        # --- Bottom: find body end (scan from bottom, only below body_top) ---
        # First, find the last row with content (trim trailing whitespace)
        last_content_row = body_top
        for y in range(height - 1, body_top - 1, -1):
            if has_content[y]:
                last_content_row = y
                break

        # Then check if there's a footer separated by a gap and skip it
        body_bottom = last_content_row + 1
        in_content = False
        gap_start = None
        for y in range(last_content_row, body_top - 1, -1):
            if has_content[y]:
                if gap_start is not None and (gap_start - y) >= min_gap:
                    body_bottom = y + 1
                    break
                in_content = True
                gap_start = None
            else:
                if in_content and gap_start is None:
                    gap_start = y

        # Horizontal bounds from the body region only
        body_mask = mask[body_top:body_bottom, :]
        if not body_mask.any():
            return fallback
        cols = np.any(body_mask, axis=0)
        left = int(np.argmax(cols))
        right = int(width - np.argmax(cols[::-1]))

        # Add padding
        pad_x = int(width * pad_frac)
        pad_y = int(height * pad_frac)
        return (
            max(0, left - pad_x), max(0, body_top - pad_y),
            min(width, right + pad_x), min(height, body_bottom + pad_y),
        )
    except Exception:
        return fallback


def _split_image_into_tiles(
    image_bytes: bytes, width: int, height: int, mode: str = "none"
) -> Tuple[List[Tuple[bytes, int, int]], List[int]]:
    """Split an image into tiles based on the requested mode.
    Modes:
      - "none": Default tall-image vertical splitting.
      - "two_columns": 2-column split with margin reduction (dictionary mode).
      - "four_quadrants": 2x2 grid split for high-res OCR.
    
    Returns (tiles, boundary_ys) where:
      tiles = list of (tile_bytes, tile_width, tile_height)
      boundary_ys = list of y-coordinates where tiles were split (in original image coords)
    """
    img = Image.open(BytesIO(image_bytes))
    fmt = img.format or "PNG"
    tiles = []
    boundary_ys = []

    if mode == "two_columns":
        # Dictionary mode: auto-detect body content, then split into two overlapping columns.
        left, top, right, bottom = _detect_content_bbox(img, pad_frac=0.01)
        inner_w = right - left
        inner_h = bottom - top

        # 5% overlap at the center so gutter text isn't lost
        overlap = int(inner_w * 0.05)
        col_w = inner_w // 2
        # Left column: includes overlap into the right half
        crop_l = img.crop((left, top, left + col_w + overlap, bottom))
        # Right column: includes overlap into the left half
        crop_r = img.crop((left + col_w - overlap, top, right, bottom))
        
        for crop in [crop_l, crop_r]:
            buf = BytesIO()
            crop.save(buf, format=fmt)
            tiles.append((buf.getvalue(), crop.width, crop.height))
            
    elif mode == "full_page_clipped":
        # Full page: auto-detect content bounding box and crop to it with a small pad.
        # Unlike column mode, we don't need a fixed % margin — just trim whitespace.
        crop_box = _detect_content_bbox(img, pad_frac=0.01)
        crop = img.crop(crop_box)
        buf = BytesIO()
        crop.save(buf, format=fmt)
        tiles.append((buf.getvalue(), crop.width, crop.height))
            
    elif mode == "four_quadrants":
        # 2x2 split
        # Reduce margins slightly (5%)
        mx = int(width * 0.05)
        my = int(height * 0.05)
        inner_w = width - 2 * mx
        inner_h = height - 2 * my
        
        cw = inner_w // 2
        ch = inner_h // 2
        
        # Quadrants: Top-Left, Top-Right, Bottom-Left, Bottom-Right
        quads = [
            (mx, my, mx + cw, my + ch),
            (mx + cw, my, mx + inner_w, my + ch),
            (mx, my + ch, mx + cw, my + inner_h),
            (mx + cw, my + ch, mx + inner_w, my + inner_h)
        ]
        
        for q in quads:
            crop = img.crop(q)
            buf = BytesIO()
            crop.save(buf, format=fmt)
            tiles.append((buf.getvalue(), crop.width, crop.height))
        
        boundary_ys.append(my + ch)
        
    else:
        # Default: split very tall images into overlapping vertical tiles
        n_tiles = max(2, math.ceil(height / TILE_TARGET_HEIGHT))
        tile_h = math.ceil(height / n_tiles)
        for i in range(n_tiles):
            y_start = max(0, i * tile_h - TILE_OVERLAP) if i > 0 else 0
            y_end = min(height, (i + 1) * tile_h)
            if i > 0:
                boundary_ys.append(i * tile_h)
            crop = img.crop((0, y_start, width, y_end))
            buf = BytesIO()
            crop.save(buf, format=fmt)
            tiles.append((buf.getvalue(), width, y_end - y_start))

    img.close()
    return tiles, boundary_ys


def _draw_tile_boundaries(image_path: str, boundary_ys: List[int], scale: float = 1.0) -> None:
    """Draw horizontal marker lines on the saved image at tile boundary positions."""
    from PIL import ImageDraw

    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    w = img.size[0]

    for y in boundary_ys:
        # Scale back to original image coordinates if image was scaled for OCR
        real_y = int(y / scale) if scale < 1.0 else y
        if real_y >= img.size[1]:
            continue
        # Draw a dashed-style red line (2px thick)
        for dy in range(2):
            draw.line([(0, real_y + dy), (w, real_y + dy)], fill=(255, 0, 0, 180), width=1)

    img.save(image_path)
    img.close()


def _find_overlap(text_a: str, text_b: str, min_overlap: int = 20) -> Tuple[int, int]:
    """Find the longest common substring between the tail of text_a and the
    head of text_b.  This handles cases where the VLM produces slightly
    different transcriptions of the same overlap region.

    Returns (end_pos_in_a, start_pos_in_b) — the merge point.
    text_a[:end_pos_in_a] + text_b[start_pos_in_b:] gives the merged text.
    Returns (len(text_a), 0) if no significant overlap found (= simple concat).
    """
    from difflib import SequenceMatcher

    # Only compare the tail of A and head of B (overlap can't be huge)
    tail_len = min(len(text_a), 1500)
    head_len = min(len(text_b), 1500)
    tail = text_a[-tail_len:]
    head = text_b[:head_len]

    sm = SequenceMatcher(None, tail, head, autojunk=False)
    match = sm.find_longest_match(0, len(tail), 0, len(head))

    if match.size < min_overlap:
        return (len(text_a), 0)

    # The matching block is at tail[match.a : match.a + match.size]
    # and head[match.b : match.b + match.size].
    # We keep text_a up to the START of the match in A,
    # and text_b from the END of the match in B (to avoid duplication).
    # But actually we want: keep A up to end of match, skip B up to end of match.
    end_in_a = len(text_a) - tail_len + match.a + match.size
    start_in_b = match.b + match.size

    return (end_in_a, start_in_b)


def _merge_tile_results(tile_results: List[Dict]) -> Dict:
    """Merge OCR results from multiple tiles of the same image.
    Uses fuzzy overlap detection (longest common substring) to deduplicate
    text from the overlapping regions between adjacent tiles.
    """
    if not tile_results:
        return {"lines": [], "dimensions": []}
    if len(tile_results) == 1:
        return tile_results[0]

    # Build merged text by finding and removing overlapping portions
    tile_texts = ["\n".join(r.get("lines", [])) for r in tile_results]
    merged = tile_texts[0]

    for i in range(1, len(tile_texts)):
        cur = tile_texts[i]
        # If both sides are empty, nothing to do
        if not merged.strip() and not cur.strip():
            continue
        if not merged.strip():
            merged = cur
            continue
        if not cur.strip():
            # Empty tile: insert a marker so we know content may be missing
            logger.warning(f"Tile merge: tile {i} returned empty — content may be lost")
            merged = merged + "\n" + TILE_MERGE_MARKER + " [TILE {0} EMPTY]".format(i)
            continue

        end_a, start_b = _find_overlap(merged, cur)
        if end_a < len(merged) or start_b > 0:
            # Sanity check: if we would drop more than 60% of cur, the overlap
            # is likely a false positive from repeated patterns
            kept_from_cur = len(cur) - start_b
            if kept_from_cur < len(cur) * 0.4:
                logger.warning(
                    f"Tile merge: overlap between tile {i-1} and {i} looks suspicious "
                    f"(would keep only {kept_from_cur}/{len(cur)} chars from tile {i}), "
                    f"falling back to simple concat"
                )
                merged = merged + "\n" + TILE_MERGE_MARKER + "\n" + cur
            else:
                overlap_chars = (len(merged) - end_a) + start_b
                logger.info(f"Tile merge: removed ~{overlap_chars}-char overlap between tile {i-1} and {i}")
                merged = merged[:end_a] + "\n" + TILE_MERGE_MARKER + "\n" + cur[start_b:]
        else:
            # Fallback: check whole-line dedup
            prev_lines = merged.split("\n")
            tile_lines = cur.split("\n")
            if prev_lines and tile_lines and prev_lines[-1].strip() == tile_lines[0].strip():
                logger.info(f"Tile merge: removed duplicate line between tile {i-1} and {i}")
                merged = merged + "\n" + TILE_MERGE_MARKER + "\n" + "\n".join(tile_lines[1:])
            else:
                merged = merged + "\n" + TILE_MERGE_MARKER + "\n" + cur

    merged_lines = [l for l in merged.split("\n") if l.strip()]

    # Re-estimate dimensions from total tile height
    from common.ocr_prompts import _estimate_dimensions
    total_h = 0
    total_w = 0
    for r in tile_results:
        dims = r.get("dimensions", [])
        if dims:
            last_d = dims[-1]
            total_h += last_d.y + last_d.height
            if not total_w:
                total_w = dims[0].width
    merged_dims = _estimate_dimensions(merged_lines, total_w, total_h) if merged_lines else []

    return {"lines": merged_lines, "dimensions": merged_dims}


class BatchRecognitionHandler:
    BATCH_JOBS_COLLECTION = "batch_recognition_jobs"

    def __init__(self):
        self._db = MongoClient.get_db()
        self._active_jobs: Dict[str, Dict] = {}
        self._cancelled_jobs: Set[str] = set()
        self._executor = ThreadPoolExecutor(max_workers=3)
        # Clean up stale jobs from previous server session
        self._cleanup_stale_jobs()

    def _cleanup_stale_jobs(self):
        """Mark any 'running' or 'pending' jobs as 'failed' on startup.
        These are leftovers from a previous server session that didn't finish cleanly."""
        collection = self._db[self.BATCH_JOBS_COLLECTION]
        stale = collection.find_many({"status": "running"}) + collection.find_many({"status": "pending"})
        for job in stale:
            collection.update_one(
                {"_id": job["_id"]},
                {"$set": {"status": "failed", "error": "Server restarted", "completed_at": datetime.utcnow().isoformat()}}
            )
        if stale:
            logger.info(f"Cleaned up {len(stale)} stale batch job(s) from previous session")

    @staticmethod
    def _scan_local_folder(folder_path: str) -> List[str]:
        """Scan a local folder for image files, return sorted filenames."""
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return []
        return sorted(
            f.name for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        )

    @staticmethod
    def _extract_class_name(filename: str) -> Optional[str]:
        """Extract YOLO class name from filename.
        Convention: {base}-{page}-{order}-{className}.ext
        The class name is the last hyphen-separated segment before the extension.
        """
        stem = Path(filename).stem
        parts = stem.split("-")
        if len(parts) >= 2:
            return parts[-1]
        return None

    @staticmethod
    def _detect_already_processed(destination_dataset_id: int, source_name: str) -> Set[str]:
        """Scan destination dataset for texts whose publication_id matches source filenames.
        Returns a set of filenames that already have entries in the destination.
        """
        try:
            dest_texts = global_new_text_handler._collection.find_many(
                find_filter={"dataset_id": int(destination_dataset_id)},
                limit=10000,
            )
            # publication_id format is "{source_name}/{filename}"
            already_done = set()
            for t in dest_texts:
                pub_id = t.get("publication_id", "")
                if "/" in pub_id:
                    already_done.add(pub_id.split("/")[-1])
                elif pub_id:
                    already_done.add(pub_id)
            return already_done
        except Exception as e:
            logger.warning(f"Could not scan destination dataset {destination_dataset_id}: {e}")
            return set()

    @staticmethod
    def _detect_already_exported(destination_folder_path: str) -> Set[str]:
        """Scan destination folder for .txt files that match source image filenames.
        Returns a set of stems (without extension) that already have text output.
        The caller filters source filenames by checking if their stem is in this set.
        """
        try:
            export_dir = Path(destination_folder_path)
            if not export_dir.exists():
                return set()
            # Each exported image produces a {stem}.txt file
            return {
                f.stem for f in export_dir.iterdir()
                if f.is_file() and f.suffix.lower() == ".txt"
            }
        except Exception as e:
            logger.warning(f"Could not scan export folder {destination_folder_path}: {e}")
            return set()

    async def start_batch(
        self,
        source_project_id: Optional[str] = None,
        source_folder_path: Optional[str] = None,
        include_classes: Optional[List[str]] = None,
        model: str = "nemotron",
        prompt: str = "dictionary",
        custom_prompt: Optional[str] = None,
        api_key: Optional[str] = None,
        sub_model: Optional[str] = None,
        batch_size: int = 0,
        destination_dataset_id: Optional[int] = None,
        destination_folder_path: Optional[str] = None,
        export_images: bool = False,
        user_id: str = "admin",
        correction_rules: Optional[str] = None,
        image_scale: Optional[float] = None,
        target_dpi: Optional[int] = None,
        include_filenames: Optional[List[str]] = None,
        exclude_filenames: Optional[List[str]] = None,
        box_mode: Optional[str] = None,
        tiling_mode: str = "none",
    ) -> Dict:
        """Start a batch recognition job asynchronously.
        Source can be a Library project (source_project_id) or a local folder (source_folder_path).
        """
        source_name = ""
        image_filenames: List[str] = []
        local_folder = None  # Set when using local folder mode

        if source_folder_path:
            # Local folder mode
            folder = Path(source_folder_path)
            if not folder.exists() or not folder.is_dir():
                return {"success": False, "job_id": None, "message": f"Folder not found: {source_folder_path}"}

            image_filenames = self._scan_local_folder(source_folder_path)
            if not image_filenames:
                return {"success": False, "job_id": None, "message": "Folder has no image files"}

            source_name = folder.name
            local_folder = str(folder)
        elif source_project_id:
            # Library project mode (existing behavior)
            pages_handler = PagesHandler()
            project = pages_handler.get_project(source_project_id)
            if project is None:
                return {"success": False, "job_id": None, "message": f"Source project '{source_project_id}' not found"}

            image_filenames = [p.filename for p in project.pages]
            if not image_filenames:
                return {"success": False, "job_id": None, "message": "Source project has no images"}

            source_name = project.name
        else:
            return {"success": False, "job_id": None, "message": "Either source_project_id or source_folder_path is required"}

        # Filter by YOLO class names if specified
        if include_classes:
            class_set = set(include_classes)
            image_filenames = [
                f for f in image_filenames
                if self._extract_class_name(f) in class_set
            ]
            if not image_filenames:
                return {"success": False, "job_id": None, "message": "No images match the selected classes"}

        # Include only specific filenames if provided (selective batch)
        if include_filenames:
            include_set = set(include_filenames)
            image_filenames = [f for f in image_filenames if f in include_set]
            if not image_filenames:
                return {"success": False, "job_id": None, "message": "None of the selected files were found in the source"}
            logger.info(f"Selective batch: {len(image_filenames)} of {len(include_set)} requested files found")

        # Auto-detect already-processed files by scanning the destination dataset/folder.
        # This works for fresh batches too — not just re-runs with exclude_filenames.
        auto_skipped = 0
        if destination_dataset_id:
            already_in_dest = self._detect_already_processed(destination_dataset_id, source_name)
            if already_in_dest:
                before = len(image_filenames)
                image_filenames = [f for f in image_filenames if f not in already_in_dest]
                auto_skipped = before - len(image_filenames)
                if auto_skipped > 0:
                    logger.info(f"Auto-skipped {auto_skipped} files already in destination dataset {destination_dataset_id}")
                if not image_filenames:
                    return {"success": False, "job_id": None, "message": f"All {auto_skipped} images already exist in the destination dataset"}

        if destination_folder_path:
            already_exported = self._detect_already_exported(destination_folder_path)
            if already_exported:
                before = len(image_filenames)
                image_filenames = [f for f in image_filenames if Path(f).stem not in already_exported]
                folder_skipped = before - len(image_filenames)
                auto_skipped += folder_skipped
                if folder_skipped > 0:
                    logger.info(f"Auto-skipped {folder_skipped} files already exported to {destination_folder_path}")
                if not image_filenames:
                    return {"success": False, "job_id": None, "message": f"All images already exported to destination folder"}

        # Exclude explicitly provided filenames (for resuming truncated batches)
        # Cross-reference against destination dataset to detect deleted texts
        if exclude_filenames:
            exclude_set = set(exclude_filenames)
            if destination_dataset_id:
                try:
                    dest_texts = global_new_text_handler._collection.find_many(
                        find_filter={"dataset_id": int(destination_dataset_id)},
                        limit=10000,
                    )
                    existing_pubs = {
                        t.get("publication_id", "").split("/")[-1]
                        for t in dest_texts
                        if t.get("publication_id")
                    }
                    deleted = exclude_set - existing_pubs
                    if deleted:
                        logger.info(f"Re-including {len(deleted)} files deleted from destination: {sorted(deleted)[:5]}...")
                        exclude_set -= deleted
                except Exception as e:
                    logger.warning(f"Could not verify destination texts: {e}")
            image_filenames = [f for f in image_filenames if f not in exclude_set]
            if not image_filenames:
                return {"success": False, "job_id": None, "message": "All images have already been processed"}
            logger.info(f"Excluded {len(exclude_set)} already-processed files, {len(image_filenames)} remaining")

        total_images = len(image_filenames)
        # batch_size < 0 (e.g. -1) means dynamic batching (by image size);
        # 0 or 1 = one at a time; >1 = fixed batch of that size
        if batch_size >= 0:
            batch_size = max(1, batch_size)

        # Build effective model name
        effective_model = model
        if sub_model and model in ("gemini_vision", "claude_vision", "gpt4_vision"):
            effective_model = f"{model}:{sub_model}"

        # Resolve prompt: custom text overrides prompt key
        from common.ocr_prompts import resolve_prompt
        if custom_prompt and custom_prompt.strip():
            resolved_prompt = custom_prompt.strip()
            prompt_label = "custom"
        else:
            resolved_prompt = resolve_prompt(prompt)
            prompt_label = prompt

        # Validate export folder if provided
        if destination_folder_path:
            export_dir = Path(destination_folder_path)
            if not export_dir.exists() or not export_dir.is_dir():
                return {"success": False, "job_id": None, "message": f"Export folder not found: {destination_folder_path}"}

        # Create job ID early (needed for GPU lock owner name)
        job_id = str(uuid.uuid4())[:8]

        # Determine if this model needs the GPU lock.
        # Cloud providers and vLLM manage their own resources externally.
        _no_gpu_lock_prefixes = ("gemini", "openai", "gpt", "anthropic", "claude", "nemotron_cloud", "vllm")
        model_lower = effective_model.lower().split(":")[0]
        uses_gpu = not any(model_lower.startswith(prefix) for prefix in _no_gpu_lock_prefixes)
        job_record = {
            "_id": job_id,
            "job_id": job_id,
            "source_project_id": source_project_id,
            "source_folder_path": local_folder,
            "source_project_name": source_name,
            "destination_dataset_id": destination_dataset_id,
            "destination_folder_path": destination_folder_path,
            "export_images": export_images,
            "include_classes": include_classes,
            "model": model,
            "effective_model": effective_model,
            "prompt": prompt_label,
            "batch_size": batch_size,
            "status": "pending",
            "current_image": 0,
            "total_images": total_images,
            "processed_images": 0,
            "failed_images": 0,
            "progress_percent": 0,
            "current_filename": "",
            "results": [],
            "failed_results": [],
            "error": None,
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
            "image_scale": image_scale,
            "target_dpi": target_dpi,
            "correction_rules": correction_rules,
            "box_mode": box_mode or "estimate",
            "tiling_mode": tiling_mode,
        }

        self._db[self.BATCH_JOBS_COLLECTION].insert_one(job_record)
        self._active_jobs[job_id] = job_record

        # Start in background thread
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            self._executor,
            self._run_batch,
            job_id,
            source_project_id,
            local_folder,
            source_name,
            image_filenames,
            effective_model,
            resolved_prompt,
            api_key,
            total_images,
            user_id,
            destination_dataset_id,
            destination_folder_path,
            export_images,
            correction_rules,
            uses_gpu,
            image_scale,
            batch_size,
            box_mode or "estimate",
            tiling_mode,
            target_dpi,
        )

        logger.info(f"Started batch recognition job {job_id}: {source_name} ({total_images} images) with model {effective_model}, batch_size={batch_size}")

        msg = "Batch recognition job started"
        if auto_skipped > 0:
            msg = f"Batch recognition job started ({auto_skipped} already-processed files skipped)"

        return {
            "success": True,
            "job_id": job_id,
            "total_images": total_images,
            "auto_skipped": auto_skipped,
            "message": msg,
        }

    def _run_batch(
        self,
        job_id: str,
        source_project_id: Optional[str],
        local_folder: Optional[str],
        source_name: str,
        image_filenames: List[str],
        effective_model: str,
        prompt: str,
        api_key: Optional[str],
        total_images: int,
        user_id: str,
        destination_dataset_id: Optional[int] = None,
        destination_folder_path: Optional[str] = None,
        export_images: bool = False,
        correction_rules: Optional[str] = None,
        uses_gpu: bool = True,
        image_scale: Optional[float] = None,
        batch_size: int = 1,
        box_mode: str = "estimate",
        tiling_mode: str = "none",
        target_dpi: Optional[int] = None,
    ):
        """Run batch recognition in a background thread.
        Supports both Library projects (source_project_id) and local folders (local_folder).
        Can export results to a local folder (destination_folder_path).
        Images are grouped into chunks of batch_size and sent together in one VLM call.
        """
        try:
            # Acquire GPU lock for local models (waits in queue if busy)
            if uses_gpu:
                import time as _time
                from services.gpu_lock import acquire as gpu_acquire
                gpu_owner_name = f"batch_recognition_{job_id}"
                self._update_status(job_id, "pending", current_filename="Waiting for GPU...")
                while True:
                    # Check for cancellation while waiting
                    if job_id in self._cancelled_jobs:
                        self._cancelled_jobs.discard(job_id)
                        self._update_status(job_id, "cancelled", completed_at=datetime.utcnow().isoformat())
                        logger.info(f"Batch job {job_id} cancelled while waiting for GPU")
                        return
                    ok, owner = gpu_acquire(gpu_owner_name)
                    if ok:
                        break
                    _time.sleep(2)  # Poll every 2 seconds

            self._update_status(job_id, "running", started_at=datetime.utcnow().isoformat())

            pages_handler = None
            if source_project_id and not local_folder:
                pages_handler = PagesHandler()

            # destination_dataset_id is already an int from the DTO
            dest_did = destination_dataset_id

            # Prepare export folder if specified
            export_folder = None
            if destination_folder_path:
                export_folder = Path(destination_folder_path)
                export_folder.mkdir(parents=True, exist_ok=True)
                if export_images:
                    (export_folder / "images").mkdir(exist_ok=True)

            ocr_client = OCRFactory.get_client(
                provider_name=effective_model,
                api_key=api_key,
            )

            # Set up a cancel event so rate-limit waits can be interrupted
            cancel_event = threading.Event()
            self._active_jobs[job_id]["cancel_event"] = cancel_event
            if hasattr(ocr_client, "set_cancel_event"):
                ocr_client.set_cancel_event(cancel_event)

            processed = 0
            failed = 0
            results = []
            failed_results = []

            from utils.image_resize import resize_image_bytes, resize_to_target_dpi
            from common.app_settings import get_image_scale, get_target_dpi

            # Determine resize strategy: DPI-aware OR scale, not both.
            # DPI takes priority — scale is only used when no DPI target is set.
            effective_target_dpi = target_dpi if target_dpi else get_target_dpi()
            use_dpi_resize = (effective_target_dpi and effective_target_dpi > 0)
            if use_dpi_resize:
                effective_scale = 1.0  # DPI resize handles reduction; ignore scale
            else:
                effective_scale = image_scale if image_scale is not None else get_image_scale()
            resizing_enabled = use_dpi_resize or (effective_scale < 1.0)

            # ── Build chunk list ──
            # Dynamic mode (batch_size < 0): pre-scan images, classify by height,
            # group by category, then chunk each group by its optimal batch size.
            # Fixed mode (batch_size > 0): simple sequential chunking as before.
            dynamic_mode = (batch_size < 0)
            if dynamic_mode:
                self._update_status(job_id, "running", current_filename="Analyzing image sizes...")
                chunk_list = self._build_dynamic_chunks(
                    job_id, image_filenames, local_folder, source_project_id,
                    pages_handler, effective_scale,
                    effective_target_dpi if use_dpi_resize else 0,
                )
                logger.info(f"Batch job {job_id}: dynamic batching → {len(chunk_list)} chunks")
            else:
                chunk_list = []
                for i in range(0, len(image_filenames), batch_size):
                    chunk_list.append(image_filenames[i:i + batch_size])

            tiled_filenames: Dict[str, str] = {}  # filename -> label ("clipped" for full_page_clipped, "tiled" for true multi-tile splits)
            tiled_boundaries: Dict[str, List[int]] = {}  # filename -> tile boundary y-coords
            images_seen = 0
            for chunk_filenames in chunk_list:

                # Check for cancellation before each chunk
                if job_id in self._cancelled_jobs:
                    self._cancelled_jobs.discard(job_id)
                    self._update_status(
                        job_id, "cancelled",
                        completed_at=datetime.utcnow().isoformat(),
                        processed_images=processed,
                        failed_images=failed,
                        results=results,
                        failed_results=failed_results,
                    )
                    logger.info(f"Batch job {job_id} cancelled at image {images_seen+1}/{total_images}")
                    return

                # Update progress at start of chunk
                self._update_status(
                    job_id, "running",
                    current_image=images_seen + 1,
                    current_filename=chunk_filenames[0],
                    progress_percent=round((images_seen / total_images) * 100, 1),
                    processed_images=processed,
                    failed_images=failed,
                )

                # Phase 1: Load all images in this chunk
                # Each entry: (filename, file_path, image_base64, width, height)
                chunk_images = []
                for filename in chunk_filenames:
                    try:
                        if local_folder:
                            file_path = os.path.join(local_folder, filename)
                            if not os.path.isfile(file_path):
                                logger.warning(f"Batch job {job_id}: image not found: {file_path}")
                                failed += 1
                                failed_results.append({"filename": filename, "error": "File not found"})
                                continue
                        else:
                            file_path = pages_handler.get_file_path(source_project_id, filename)
                            if not file_path:
                                logger.warning(f"Batch job {job_id}: image not found: {filename}")
                                failed += 1
                                failed_results.append({"filename": filename, "error": "File not found in library"})
                                continue

                        with open(file_path, "rb") as f:
                            image_bytes = f.read()

                        # Get original dimensions before any resizing
                        orig_img = Image.open(BytesIO(image_bytes))
                        orig_w, orig_h = orig_img.size
                        orig_img.close()

                        if use_dpi_resize:
                            image_bytes, _ = resize_to_target_dpi(image_bytes, effective_target_dpi)
                        elif effective_scale < 1.0:
                            image_bytes = resize_image_bytes(image_bytes, effective_scale)

                        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                        img = Image.open(BytesIO(image_bytes))
                        w, h = img.size
                        img.close()

                        chunk_images.append((filename, file_path, image_base64, w, h, orig_w, orig_h))
                    except Exception as e:
                        logger.error(f"Batch job {job_id}: failed to load {filename}: {e}")
                        failed += 1
                        failed_results.append({"filename": filename, "error": str(e)})

                if not chunk_images:
                    continue

                # Phase 2: OCR call
                try:
                    if len(chunk_images) == 1:
                        fn, fp, b64, w, h, ow, oh = chunk_images[0]
                        # Tiling: split images into multiple parts if requested or if very tall
                        wants_tiling = tiling_mode != "none" or (dynamic_mode and h > TILE_TARGET_HEIGHT)
                        
                        if wants_tiling:
                            # full_page_clipped produces a single tile (auto-cropped margins),
                            # so it's "clipped" rather than truly "tiled". Real multi-tile
                            # modes (two_columns, four_quadrants, tall-image splits) → "tiled".
                            tiled_filenames[fn] = "clipped" if tiling_mode == "full_page_clipped" else "tiled"
                            mode_label = tiling_mode if tiling_mode != "none" else "tall"
                            logger.info(f"Batch job {job_id}: splitting {fn} ({w}x{h}) into {mode_label} tiles")
                            self._update_status(job_id, "running", current_filename=f"Tiling {fn} ({mode_label})...")
                            image_bytes_for_tile = base64.b64decode(b64)
                            tiles, boundary_ys = _split_image_into_tiles(image_bytes_for_tile, w, h, mode=tiling_mode)
                            tiled_boundaries[fn] = boundary_ys
                            tile_results = []
                            for ti, (tile_bytes, tw, th) in enumerate(tiles):
                                # Check cancellation between tiles
                                if job_id in self._cancelled_jobs:
                                    raise GeminiCancelledError("Cancelled between tiles")
                                tile_b64 = base64.b64encode(tile_bytes).decode("utf-8")
                                tile_result = ocr_client.ocr_image(tile_b64, tw, th, prompt)
                                # Retry up to 2 times if tile returned empty/headers-only or was truncated
                                tile_lines = tile_result.get("lines", [])
                                if not _has_real_content(tile_lines) or tile_result.get("truncated"):
                                    import time
                                    for retry_i in range(1, 3):
                                        reason = "truncated" if tile_result.get("truncated") else "empty/headers-only"
                                        logger.warning(f"  Tile {ti+1}/{len(tiles)}: {reason} result, retry {retry_i}/2...")
                                        time.sleep(2 * retry_i)
                                        tile_result = ocr_client.ocr_image(tile_b64, tw, th, prompt)
                                        if _has_real_content(tile_result.get("lines", [])) and not tile_result.get("truncated"):
                                            break
                                tile_results.append(tile_result)
                                logger.info(f"  Tile {ti+1}/{len(tiles)}: {len(tile_result.get('lines', []))} lines")
                            merged = _merge_tile_results(tile_results)
                            logger.info(f"  Merged tiles: {len(merged.get('lines', []))} total lines")
                            ocr_results = [merged]
                        else:
                            ocr_results = [ocr_client.ocr_image(b64, w, h, prompt)]
                    else:
                        image_tuples = [(b64, w, h) for _, _, b64, w, h, _, _ in chunk_images]
                        ocr_results = ocr_client.ocr_images(image_tuples, prompt)

                        # Phase 2.5: Detect merge failure and try to redistribute.
                        # Pattern: first image gets all text, rest are empty.
                        empty_count = sum(1 for r in ocr_results if not r.get("lines"))
                        if empty_count > 0 and empty_count >= len(chunk_images) - 1:
                            # Collect all lines from the non-empty result(s)
                            merged_lines = []
                            for r in ocr_results:
                                merged_lines.extend(r.get("lines", []))

                            n_chunk = len(chunk_images)
                            if len(merged_lines) == n_chunk:
                                # Line count matches image count — distribute 1:1
                                logger.info(
                                    f"Batch job {job_id}: merge failure in chunk {chunk_filenames[0]}, "
                                    f"redistributing {len(merged_lines)} lines to {n_chunk} images"
                                )
                                from common.ocr_prompts import _estimate_dimensions
                                ocr_results = []
                                for ci_idx, (_, _, _, ci_w, ci_h, _, _) in enumerate(chunk_images):
                                    line = [merged_lines[ci_idx]]
                                    ocr_results.append({
                                        "lines": line,
                                        "dimensions": _estimate_dimensions(line, ci_w, ci_h),
                                    })
                            else:
                                # Line count doesn't match — retry in smaller sub-batches
                                sub_batch_size = max(1, n_chunk // 2)
                                logger.info(
                                    f"Batch job {job_id}: merge failure in chunk {chunk_filenames[0]} "
                                    f"({len(merged_lines)} lines vs {n_chunk} images), retrying in sub-batches of {sub_batch_size}"
                                )
                                self._update_status(
                                    job_id, "running",
                                    current_filename=f"Re-processing {chunk_filenames[0]} in sub-batches...",
                                )
                                retry_results = []
                                for sb_start in range(0, n_chunk, sub_batch_size):
                                    sb_images = chunk_images[sb_start:sb_start + sub_batch_size]
                                    try:
                                        if len(sb_images) == 1:
                                            r_fn, r_fp, r_b64, r_w, r_h, _, _ = sb_images[0]
                                            retry_results.append(ocr_client.ocr_image(r_b64, r_w, r_h, prompt))
                                        else:
                                            sb_tuples = [(b64, w, h) for _, _, b64, w, h, _, _ in sb_images]
                                            retry_results.extend(ocr_client.ocr_images(sb_tuples, prompt))
                                    except Exception as re_err:
                                        logger.warning(f"  Sub-batch starting at {sb_images[0][0]} failed: {re_err}")
                                        retry_results.extend([{"lines": [], "dimensions": []} for _ in sb_images])

                                new_empty = sum(1 for r in retry_results if not r.get("lines"))
                                if new_empty < empty_count:
                                    logger.info(f"  Correction improved: {empty_count} -> {new_empty} empty results")
                                    ocr_results = retry_results
                                else:
                                    logger.info(f"  Correction did not improve ({new_empty} empty), keeping original")

                except Exception as e:
                    # If cancelled, break out of the chunk loop immediately
                    if isinstance(e, (GeminiCancelledError, AnthropicCancelledError)) or job_id in self._cancelled_jobs:
                        logger.info(f"Batch job {job_id}: cancelled during OCR call")
                        break

                    # Rate limit exhausted — stop the batch and report reset time
                    if isinstance(e, GeminiRateLimitError):
                        logger.warning(f"Batch job {job_id}: rate limit reached, stopping batch")
                        # Gemini daily limits reset at midnight Pacific Time (UTC-7/UTC-8)
                        from datetime import timezone, timedelta
                        now_utc = datetime.utcnow()
                        pacific = timezone(timedelta(hours=-7))
                        now_pacific = now_utc.replace(tzinfo=timezone.utc).astimezone(pacific)
                        midnight_pacific = (now_pacific + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                        reset_utc = midnight_pacific.astimezone(timezone.utc)
                        self._update_status(
                            job_id, "rate_limited",
                            error=str(e),
                            rate_limit_reached=True,
                            rate_limit_reset=reset_utc.isoformat(),
                            completed_at=datetime.utcnow().isoformat(),
                            processed_images=processed,
                            failed_images=failed,
                            results=results,
                            failed_results=failed_results,
                        )
                        return  # Exit the entire batch processing

                    logger.error(f"Batch job {job_id}: OCR call failed for chunk starting at {chunk_filenames[0]}: {e}")
                    for fn, fp, _, _, _, _, _ in chunk_images:
                        failed += 1
                        failed_results.append({"filename": fn, "error": f"OCR call failed: {e}"})
                    continue

                # Phase 3: Save results per image
                for idx, (filename, file_path, _, ocr_w, ocr_h, orig_w, orig_h) in enumerate(chunk_images):
                    try:
                        ocr_result = ocr_results[idx] if idx < len(ocr_results) else {"lines": [], "dimensions": []}
                        text_lines = ocr_result.get("lines", [])
                        boxes = ocr_result.get("dimensions", [])

                        text_lines = [line.replace("\n", "") for line in text_lines]

                        if correction_rules == "akkadian":
                            from utils.akkadian_ocr_corrections import correct_lines
                            text_lines = correct_lines(text_lines)

                        if not _has_real_content(text_lines) and len(chunk_images) > 1:
                            # VLM skipped this image in the batch — retry individually
                            logger.info(f"Batch job {job_id}: retrying {filename} individually (empty/headers-only in batch)")
                            try:
                                _, _, retry_b64, retry_w, retry_h, _, _ = chunk_images[idx]
                                retry_result = ocr_client.ocr_image(retry_b64, retry_w, retry_h, prompt)
                                text_lines = retry_result.get("lines", [])
                                boxes = retry_result.get("dimensions", [])
                                text_lines = [line.replace("\n", "") for line in text_lines]
                                if correction_rules == "akkadian":
                                    from utils.akkadian_ocr_corrections import correct_lines
                                    text_lines = correct_lines(text_lines)
                            except Exception as retry_err:
                                logger.warning(f"Batch job {job_id}: retry failed for {filename}: {retry_err}")

                        # Scale bounding boxes back to original image coordinates
                        if resizing_enabled and boxes and orig_w > 0 and ocr_w > 0:
                            sx = orig_w / ocr_w
                            sy = orig_h / ocr_h
                            boxes = [
                                Dimensions(x=int(b.x * sx), y=int(b.y * sy),
                                           width=int(b.width * sx), height=int(b.height * sy))
                                for b in boxes
                            ]

                        # Box mode: "none" = no boxes, "predict" = Kraken segmentation
                        if box_mode == "none":
                            boxes = []
                        elif box_mode == "predict" and text_lines:
                            try:
                                from services.segmentation_service import SegmentationService
                                with open(file_path, "rb") as img_f:
                                    img_bytes = img_f.read()
                                img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                                seg_service = SegmentationService()
                                seg_result = seg_service.segment(img_b64)
                                if seg_result.lines:
                                    boxes = seg_result.lines
                                    logger.info(f"Batch job {job_id}: Segmentation predicted {len(boxes)} boxes for {filename} (method={seg_result.method})")
                                else:
                                    logger.warning(f"Batch job {job_id}: Segmentation returned no boxes for {filename}, keeping estimated")
                            except Exception as seg_err:
                                logger.warning(f"Batch job {job_id}: Segmentation failed for {filename}: {seg_err}, keeping estimated")

                        if not _has_real_content(text_lines):
                            # Cascading retry strategy. Step 1 is the user's chosen scale +
                            # tiling mode (already executed above). Steps 2-4 escalate:
                            #   2. Same image at the alternate scale (whole page, no tiling)
                            #   3. two_columns at native resolution
                            #   4. two_columns at 50% reduction
                            if text_lines:
                                logger.info(f"Batch job {job_id}: {filename} has only structural headers {text_lines}, treating as empty")
                            import time
                            from utils.image_resize import resize_image_bytes

                            with open(file_path, "rb") as img_f:
                                orig_bytes = img_f.read()

                            # Alternate scale: if user started at native (>=1.0), retry at 50%; otherwise retry at native.
                            alt_scale = 1.0 if effective_scale < 1.0 else 0.5

                            def _post(lines):
                                cleaned = [ln.replace("\n", "") for ln in lines]
                                if correction_rules == "akkadian":
                                    from utils.akkadian_ocr_corrections import correct_lines
                                    cleaned = correct_lines(cleaned)
                                return cleaned

                            # Step 2: alternate scale, whole page (no tiling)
                            logger.info(f"Batch job {job_id}: retrying {filename} at scale={alt_scale} (whole page)")
                            time.sleep(2)
                            try:
                                step2_bytes = resize_image_bytes(orig_bytes, alt_scale) if alt_scale < 1.0 else orig_bytes
                                s2_img = Image.open(BytesIO(step2_bytes))
                                s2w, s2h = s2_img.size
                                s2_img.close()
                                step2_b64 = base64.b64encode(step2_bytes).decode("utf-8")
                                retry_result = ocr_client.ocr_image(step2_b64, s2w, s2h, prompt)
                                text_lines = _post(retry_result.get("lines", []))
                                boxes = retry_result.get("dimensions", []) if box_mode != "none" else []
                            except Exception as e1:
                                logger.warning(f"Batch job {job_id}: alt-scale ({alt_scale}) retry failed for {filename}: {e1}")

                            # Step 3: two_columns at native resolution
                            if not _has_real_content(text_lines):
                                logger.info(f"Batch job {job_id}: retrying {filename} with two_columns (native)")
                                time.sleep(2)
                                try:
                                    full_img = Image.open(BytesIO(orig_bytes))
                                    fw, fh = full_img.size
                                    full_img.close()
                                    tiles, _ = _split_image_into_tiles(orig_bytes, fw, fh, mode="two_columns")
                                    tile_results = []
                                    for tile_bytes, tw, th in tiles:
                                        tile_b64 = base64.b64encode(tile_bytes).decode("utf-8")
                                        tile_results.append(ocr_client.ocr_image(tile_b64, tw, th, prompt))
                                    merged = _merge_tile_results(tile_results)
                                    text_lines = _post(merged.get("lines", []))
                                    boxes = merged.get("dimensions", []) if box_mode != "none" else []
                                    if _has_real_content(text_lines):
                                        tiled_filenames[filename] = "tiled"
                                except Exception as e2:
                                    logger.warning(f"Batch job {job_id}: two_columns native retry failed for {filename}: {e2}")

                            # Step 4: two_columns at 50% reduction
                            if not _has_real_content(text_lines):
                                logger.info(f"Batch job {job_id}: retrying {filename} with two_columns (50% reduction)")
                                time.sleep(2)
                                try:
                                    reduced_bytes = resize_image_bytes(orig_bytes, 0.5)
                                    reduced_img = Image.open(BytesIO(reduced_bytes))
                                    rw, rh = reduced_img.size
                                    reduced_img.close()
                                    tiles, _ = _split_image_into_tiles(reduced_bytes, rw, rh, mode="two_columns")
                                    tile_results = []
                                    for tile_bytes, tw, th in tiles:
                                        tile_b64 = base64.b64encode(tile_bytes).decode("utf-8")
                                        tile_results.append(ocr_client.ocr_image(tile_b64, tw, th, prompt))
                                    merged = _merge_tile_results(tile_results)
                                    text_lines = _post(merged.get("lines", []))
                                    boxes = merged.get("dimensions", []) if box_mode != "none" else []
                                    if _has_real_content(text_lines):
                                        tiled_filenames[filename] = "tiled"
                                except Exception as e3:
                                    logger.warning(f"Batch job {job_id}: two_columns 50% retry failed for {filename}: {e3}")

                        # Two distinct failure modes after the cascade:
                        #   - Truly empty (no lines or only whitespace) → drop, no entry saved
                        #   - Headers-only ("# COLUMN A # COLUMN B" etc.) → save with "failed" label
                        truly_empty = not any((ln or "").strip() for ln in (text_lines or []))
                        if truly_empty:
                            logger.warning(f"Batch job {job_id}: no text detected in {filename} after all retries — dropping")
                            failed += 1
                            failed_results.append({"filename": filename, "error": "No text detected (all retries exhausted)"})
                            continue
                        content_failed = not _has_real_content(text_lines)
                        if content_failed:
                            logger.warning(f"Batch job {job_id}: only structural headers in {filename} after all retries (lines={text_lines}) — saving with 'failed' label")

                        pub_id = f"{source_name}/{filename}"

                        # Dedup: skip if a text with this publication_id already exists in the destination
                        if dest_did:
                            existing = global_new_text_handler._collection.find_many(
                                find_filter={"dataset_id": int(dest_did), "publication_id": pub_id},
                                limit=1,
                            )
                            if existing:
                                logger.info(f"Batch job {job_id}: skipping {filename} — already exists in dataset {dest_did} (text_id={existing[0].get('text_id')})")
                                processed += 1
                                results.append({
                                    "filename": filename,
                                    "text_id": existing[0].get("text_id"),
                                    "transliteration_id": None,
                                    "lines_count": len(text_lines),
                                })
                                continue

                        identifiers = TextIdentifiersDto.from_values(
                            publication=pub_id
                        )
                        text_id = global_new_text_handler.create_new_text(
                            identifiers=identifiers,
                            metadata=[{"source": "batch_recognition", "job_id": job_id}],
                            uploader_id=user_id,
                            dataset_id=dest_did,
                        )

                        image_name = StorageUtils.generate_cured_train_image_name(
                            original_file_name=filename, text_id=text_id
                        )
                        dest_path = StorageUtils.build_cured_train_image_path(image_name=image_name)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        shutil.copy2(file_path, dest_path)

                        # Verify the copy succeeded
                        if not os.path.isfile(dest_path):
                            logger.error(
                                f"Batch job {job_id}: image copy FAILED for {filename} → {dest_path} "
                                f"(source exists: {os.path.isfile(file_path)}, "
                                f"BASE_PATH: {StorageUtils.BASE_PATH})"
                            )

                        # Draw tile boundary lines on the saved image
                        if filename in tiled_boundaries:
                            try:
                                # Compute actual scale from original vs OCR dimensions
                                img_scale = ocr_h / orig_h if orig_h > 0 else 1.0
                                _draw_tile_boundaries(dest_path, tiled_boundaries[filename], img_scale)
                            except Exception as e:
                                logger.warning(f"Failed to draw tile boundaries on {filename}: {e}")

                        preview_path = StorageUtils.build_preview_image_path(image_name=image_name)
                        StorageUtils.make_a_preview(image_path=dest_path, preview_path=preview_path)

                        submit_dto = TransliterationSubmitDto(
                            text_id=text_id,
                            lines=text_lines,
                            boxes=boxes,
                            source=TransliterationSource.CURED,
                            image_name=image_name,
                            is_curated_vlm=False,
                            is_curated_kraken=False,
                        )
                        transliteration_id = global_new_text_handler.save_new_transliteration(
                            dto=submit_dto, uploader_id=user_id
                        )

                        if export_folder:
                            stem = Path(filename).stem
                            txt_path = export_folder / f"{stem}.txt"
                            with open(txt_path, "w", encoding="utf-8") as tf:
                                tf.write("\n".join(text_lines))
                            if export_images:
                                shutil.copy2(file_path, export_folder / "images" / filename)

                        processed += 1
                        result_entry = {
                            "filename": filename,
                            "text_id": text_id,
                            "transliteration_id": transliteration_id,
                            "lines_count": len(text_lines),
                        }
                        if filename in tiled_filenames:
                            result_entry["was_tiled"] = True
                        # "failed" replaces the tiling label — a failed entry shouldn't
                        # claim to have been successfully clipped/tiled.
                        if content_failed:
                            result_entry["failed_content"] = True
                            labels_to_set = ["failed"]
                        elif filename in tiled_filenames:
                            labels_to_set = [tiled_filenames[filename]]
                        else:
                            labels_to_set = []
                        if labels_to_set:
                            try:
                                global_new_text_handler.update_labels(text_id, labels_to_set)
                            except Exception:
                                pass
                        results.append(result_entry)

                        logger.info(f"Batch job {job_id}: processed {filename} -> text_id={text_id}, {len(text_lines)} lines")

                    except Exception as e:
                        logger.error(f"Batch job {job_id}: failed to save {filename}: {e}")
                        failed += 1
                        failed_results.append({"filename": filename, "error": str(e)})

                images_seen += len(chunk_filenames)

            # Check if we broke out of the loop due to cancellation
            if job_id in self._cancelled_jobs:
                self._cancelled_jobs.discard(job_id)
                self._update_status(
                    job_id, "cancelled",
                    completed_at=datetime.utcnow().isoformat(),
                    processed_images=processed,
                    failed_images=failed,
                    results=results,
                    failed_results=failed_results,
                )
                logger.info(f"Batch job {job_id} cancelled at image {images_seen}/{total_images}")
            else:
                # Job completed
                self._update_status(
                    job_id, "completed",
                    completed_at=datetime.utcnow().isoformat(),
                    progress_percent=100,
                    current_image=total_images,
                    processed_images=processed,
                    failed_images=failed,
                    results=results,
                    failed_results=failed_results,
                    current_filename="",
                )
                logger.info(f"Batch job {job_id} completed: {processed} processed, {failed} failed out of {total_images}")

        except Exception as e:
            logger.error(f"Batch job {job_id} failed: {e}")
            self._update_status(
                job_id, "failed",
                error=str(e),
                completed_at=datetime.utcnow().isoformat(),
            )

        finally:
            if job_id in self._active_jobs:
                del self._active_jobs[job_id]
            if uses_gpu:
                from services.gpu_lock import release as gpu_release
                gpu_release(f"batch_recognition_{job_id}")

    def _build_dynamic_chunks(
        self,
        job_id: str,
        image_filenames: List[str],
        local_folder: Optional[str],
        source_project_id: Optional[str],
        pages_handler,
        effective_scale: float,
        target_dpi: int = 0,
    ) -> List[List[str]]:
        """Pre-scan images, classify by height, group by size category, chunk by optimal batch size."""
        from utils.image_resize import resize_image_bytes, resize_to_target_dpi, _get_image_dpi

        use_dpi = (target_dpi > 0)

        # category_name -> list of filenames
        buckets: Dict[str, List[str]] = defaultdict(list)
        # Track effective heights for tile calculation
        image_heights: Dict[str, int] = {}

        for filename in image_filenames:
            try:
                if local_folder:
                    file_path = os.path.join(local_folder, filename)
                else:
                    file_path = pages_handler.get_file_path(source_project_id, filename)
                if not file_path or not os.path.isfile(file_path):
                    buckets["_unknown"].append(filename)
                    continue

                with open(file_path, "rb") as f:
                    image_bytes = f.read()

                img = Image.open(BytesIO(image_bytes))
                w, h = img.size

                # Compute effective dimensions after resizing (DPI OR scale, not both)
                if use_dpi:
                    source_dpi = _get_image_dpi(img)
                    if source_dpi > target_dpi:
                        dpi_scale = target_dpi / source_dpi
                        h = int(h * dpi_scale)
                        w = int(w * dpi_scale)
                elif effective_scale < 1.0:
                    h = int(h * effective_scale)
                    w = int(w * effective_scale)

                img.close()

                image_heights[filename] = h
                cat, _ = _classify_image(h, w)
                buckets[cat].append(filename)
            except Exception:
                buckets["_unknown"].append(filename)

        # Build report of category distribution (in size order, not alphabetical)
        cat_order = [name for name, _, _, _ in SIZE_CATEGORIES] + ["_unknown"]
        category_report = []
        for cat in cat_order:
            fnames = buckets.get(cat, [])
            if fnames:
                bs = next((b for n, _, _, b in SIZE_CATEGORIES if n == cat), 1)
                n_chunks = math.ceil(len(fnames) / bs)
                # Count tiled images and total tiles for this category
                tiled_count = 0
                total_tiles = 0
                min_tiles_per_image = None
                max_tiles_per_image = None
                for fn in fnames:
                    h = image_heights.get(fn, 0)
                    if h > TILE_TARGET_HEIGHT:
                        n_tiles = max(2, math.ceil(h / TILE_TARGET_HEIGHT))
                        tiled_count += 1
                        total_tiles += n_tiles
                        if min_tiles_per_image is None or n_tiles < min_tiles_per_image:
                            min_tiles_per_image = n_tiles
                        if max_tiles_per_image is None or n_tiles > max_tiles_per_image:
                            max_tiles_per_image = n_tiles
                # API calls: non-tiled chunks + tile parts
                api_calls = (n_chunks - tiled_count) + total_tiles
                entry = {
                    "category": cat,
                    "image_count": len(fnames),
                    "batch_size": bs,
                    "tiled_count": tiled_count,
                    "min_tiles": min_tiles_per_image,
                    "max_tiles": max_tiles_per_image,
                    "api_calls": api_calls,
                }
                category_report.append(entry)
                logger.info(f"Batch job {job_id}: category '{cat}' → {len(fnames)} images, batch_size={bs}, {n_chunks} chunks, {tiled_count} tiled ({total_tiles} tiles), {api_calls} API calls")

        # Store report in job status
        self._update_status(job_id, "running", dynamic_report=category_report)

        # Build chunks: group by category, then split into sub-chunks by batch size
        cat_batch_sizes = {name: bs for name, _, _, bs in SIZE_CATEGORIES}
        cat_batch_sizes["_unknown"] = 1

        chunks: List[List[str]] = []
        for cat in cat_order:
            fnames = buckets.get(cat, [])
            if not fnames:
                continue
            bs = cat_batch_sizes.get(cat, 1)
            for i in range(0, len(fnames), bs):
                chunks.append(fnames[i:i + bs])

        return chunks

    def _update_status(self, job_id: str, status: str, **kwargs):
        """Update a batch job's status in DB and active jobs cache."""
        update = {"status": status}
        update.update(kwargs)

        self._db[self.BATCH_JOBS_COLLECTION].update_one(
            {"_id": job_id},
            {"$set": update}
        )

        if job_id in self._active_jobs:
            self._active_jobs[job_id].update(update)

    def get_batch_status(self, job_id: str) -> Dict:
        """Get the current status of a batch recognition job."""
        # Check active jobs first (more up-to-date)
        if job_id in self._active_jobs:
            job = self._active_jobs[job_id]
        else:
            job = self._db[self.BATCH_JOBS_COLLECTION].find_one({"_id": job_id})

        if not job:
            return {"success": False, "error": f"Job '{job_id}' not found"}

        return {
            "success": True,
            "job_id": job["job_id"],
            "status": job.get("status", "pending"),
            "source_project_name": job.get("source_project_name", ""),
            "model": job.get("model", ""),
            "prompt": job.get("prompt", ""),
            "current_image": job.get("current_image", 0),
            "total_images": job.get("total_images", 0),
            "processed_images": job.get("processed_images", 0),
            "failed_images": job.get("failed_images", 0),
            "progress_percent": job.get("progress_percent", 0),
            "current_filename": job.get("current_filename", ""),
            "results": job.get("results", []),
            "failed_results": job.get("failed_results", []),
            "error": job.get("error"),
            "created_at": job.get("created_at"),
            "completed_at": job.get("completed_at"),
            "batch_size": job.get("batch_size", 1),
            "dynamic_report": job.get("dynamic_report"),
            "image_scale": job.get("image_scale"),
            "target_dpi": job.get("target_dpi"),
            "started_at": job.get("started_at"),
            "source_project_id": job.get("source_project_id"),
            "source_folder_path": job.get("source_folder_path"),
            "include_classes": job.get("include_classes"),
            "destination_dataset_id": job.get("destination_dataset_id"),
            "destination_folder_path": job.get("destination_folder_path"),
            "export_images": job.get("export_images", False),
            "correction_rules": job.get("correction_rules"),
            "effective_model": job.get("effective_model"),
            "box_mode": job.get("box_mode", "estimate"),
            "tiling_mode": job.get("tiling_mode", "none"),
            "rate_limit_reached": job.get("rate_limit_reached", False),
            "rate_limit_reset": job.get("rate_limit_reset"),
        }

    def list_batch_jobs(self, limit: int = 20) -> List[Dict]:
        """List recent batch recognition jobs."""
        jobs = self._db[self.BATCH_JOBS_COLLECTION].find(
            {},
            sort=[("created_at", -1)],
            limit=limit,
        )
        return [
            {
                "job_id": job["job_id"],
                "status": job.get("status", "pending"),
                "source_project_name": job.get("source_project_name", ""),
                "model": job.get("model", ""),
                "total_images": job.get("total_images", 0),
                "processed_images": job.get("processed_images", 0),
                "failed_images": job.get("failed_images", 0),
                "progress_percent": job.get("progress_percent", 0),
                "created_at": job.get("created_at"),
                "completed_at": job.get("completed_at"),
            }
            for job in jobs
        ]

    def cancel_batch(self, job_id: str) -> Dict:
        """Cancel a running batch job."""
        if job_id in self._active_jobs:
            self._cancelled_jobs.add(job_id)
            # Signal the cancel event to interrupt any rate-limit waits
            cancel_event = self._active_jobs[job_id].get("cancel_event")
            if cancel_event:
                cancel_event.set()
            return {"success": True, "message": f"Cancellation requested for job {job_id}"}

        # Check if job exists but is already done
        job = self._db[self.BATCH_JOBS_COLLECTION].find_one({"_id": job_id})
        if not job:
            return {"success": False, "message": f"Job '{job_id}' not found"}

        if job.get("status") in ("completed", "failed", "cancelled"):
            return {"success": False, "message": f"Job '{job_id}' is already {job['status']}"}

        return {"success": False, "message": f"Job '{job_id}' is not currently running"}


# Singleton instance
batch_recognition_handler = BatchRecognitionHandler()
