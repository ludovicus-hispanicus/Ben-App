"""
Pages Handler - Manages project-based document storage with folder hierarchy.

Scans two sources for projects:
  1. STORAGE_PATH/pages/{project_id}/     — user-uploaded projects
  2. YOLO_DATA_PATH/pdf_images/{folder}/  — PDF pages from Predict

Storage layout for uploaded projects:
  STORAGE_PATH/pages/{project_id}/
    metadata.json       (name, page_count, created_at, parent_id)
    page_001.png
    page_002.png
    thumbnails/
      page_001.jpg
"""
import json
import logging
import os
import re
import random
import shutil
import string
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from api.dto.pages import PageInfo, ProjectInfo, ProjectDetail, ProjectListResponse, UploadResponse
from utils.pdf_utils import PdfUtils

logger = logging.getLogger(__name__)

# Storage paths
_storage_path = os.environ.get("STORAGE_PATH", "data")
PAGES_PATH = Path(os.path.join(_storage_path, "pages"))
PAGES_PATH.mkdir(parents=True, exist_ok=True)

# YOLO pdf_images path (converted PDFs from Predict)
YOLO_DATA_PATH = Path(os.environ.get("YOLO_DATA_PATH", os.path.join(_storage_path, "yolo")))
PDF_IMAGES_PATH = YOLO_DATA_PATH / "pdf_images"

# Prefix to distinguish pdf_images projects from uploaded ones
_PDF_IMG_PREFIX = "pdfimg__"


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    text = os.path.splitext(text)[0]
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s]+', '_', text.strip())
    return text[:50]


def _random_suffix(length: int = 6) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _resolve_project_path(project_id: str) -> Path:
    """Resolve a project_id to its filesystem path."""
    if project_id.startswith(_PDF_IMG_PREFIX):
        folder_name = project_id[len(_PDF_IMG_PREFIX):]
        return PDF_IMAGES_PATH / folder_name
    return PAGES_PATH / project_id


def _read_metadata(project_path: Path) -> dict:
    """Read metadata.json from a project directory."""
    meta_file = project_path / "metadata.json"
    if meta_file.exists():
        try:
            return json.loads(meta_file.read_text())
        except Exception:
            return {}
    return {}


def _write_metadata(project_path: Path, metadata: dict):
    """Write metadata.json to a project directory."""
    meta_file = project_path / "metadata.json"
    meta_file.write_text(json.dumps(metadata, indent=2))


class PagesHandler:

    # ============== Project Management ==============

    def create_project(self, name: str, parent_id: Optional[str] = None) -> UploadResponse:
        """Create an empty project, optionally inside a parent folder."""
        if parent_id is not None:
            parent_path = _resolve_project_path(parent_id)
            if not parent_path.exists():
                raise ValueError(f"Parent project '{parent_id}' not found")

        slug = _slugify(name)
        project_id = f"{slug}_{_random_suffix()}"
        project_path = PAGES_PATH / project_id
        project_path.mkdir(parents=True, exist_ok=True)
        (project_path / "thumbnails").mkdir(exist_ok=True)

        metadata = {
            "name": name,
            "page_count": 0,
            "created_at": datetime.now().isoformat(),
        }
        if parent_id is not None:
            metadata["parent_id"] = parent_id
        _write_metadata(project_path, metadata)

        logger.info(f"Created project '{name}' as '{project_id}' (parent={parent_id})")
        return UploadResponse(
            project_id=project_id,
            name=name,
            page_count=0,
            message=f"Created project '{name}'"
        )

    def rename_project(self, project_id: str, name: str) -> bool:
        """Rename a project."""
        project_path = _resolve_project_path(project_id)
        if not project_path.exists():
            return False
        meta = _read_metadata(project_path)
        meta["name"] = name
        _write_metadata(project_path, meta)
        return True

    def move_project(self, project_id: str, new_parent_id: Optional[str]) -> Dict:
        """Move a project to a new parent. new_parent_id=None moves to root."""
        project_path = _resolve_project_path(project_id)
        if not project_path.exists():
            return {"updated": False, "error": "Project not found"}

        if new_parent_id is not None:
            parent_path = _resolve_project_path(new_parent_id)
            if not parent_path.exists():
                return {"updated": False, "error": "Target folder not found"}
            # Cycle detection
            current = new_parent_id
            visited = set()
            while current is not None:
                if current == project_id:
                    return {"updated": False, "error": "Cannot move into itself or descendants"}
                if current in visited:
                    break
                visited.add(current)
                p_path = _resolve_project_path(current)
                p_meta = _read_metadata(p_path)
                current = p_meta.get("parent_id")

        meta = _read_metadata(project_path)
        old_parent = meta.get("parent_id")
        if new_parent_id is None:
            meta.pop("parent_id", None)
        else:
            meta["parent_id"] = new_parent_id
        _write_metadata(project_path, meta)
        logger.info(f"Moved project '{project_id}': parent_id {old_parent!r} -> {new_parent_id!r} (path={project_path})")

        # Verify write
        verify = _read_metadata(project_path)
        logger.info(f"Verified metadata after write: parent_id={verify.get('parent_id')!r}")

        return {"updated": True}

    # ============== Upload ==============

    def _next_page_number(self, project_path: Path) -> int:
        """Get the next available page number in a project."""
        existing = list(project_path.glob("page_*.png"))
        if not existing:
            return 1
        nums = []
        for p in existing:
            try:
                nums.append(int(p.stem.replace("page_", "")))
            except ValueError:
                pass
        return max(nums) + 1 if nums else 1

    def upload_pdf(self, pdf_bytes: bytes, filename: str, project_id: str = None,
                   project_name: str = None, page_from: int = None, page_to: int = None,
                   dpi: int = None) -> UploadResponse:
        """Upload a PDF, convert pages to PNG. Creates new project or adds to existing.

        Args:
            page_from: First page to extract (1-indexed, inclusive). None = start from page 1.
            page_to: Last page to extract (1-indexed, inclusive). None = extract to last page.
            dpi: Resolution for PDF rendering. None = default (150).
        """
        if project_id:
            project_path = _resolve_project_path(project_id)
            if not project_path.exists():
                raise FileNotFoundError(f"Project '{project_id}' not found")
        else:
            slug = _slugify(project_name or filename)
            project_id = f"{slug}_{_random_suffix()}"
            project_path = PAGES_PATH / project_id
            project_path.mkdir(parents=True, exist_ok=True)

        thumbs_path = project_path / "thumbnails"
        thumbs_path.mkdir(exist_ok=True)

        pages = PdfUtils.extract_all_pages(pdf_bytes, page_from=page_from, page_to=page_to, dpi=dpi)
        start_num = self._next_page_number(project_path)

        for i, png_bytes in enumerate(pages):
            page_num = start_num + i
            page_path = project_path / f"page_{page_num:03d}.png"
            page_path.write_bytes(png_bytes)

            thumb_path = thumbs_path / f"page_{page_num:03d}.jpg"
            self._make_thumbnail(str(page_path), str(thumb_path))

        # Save original PDF
        (project_path / filename).write_bytes(pdf_bytes)

        # Update metadata
        total_pages = len([
            p for p in project_path.iterdir()
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")
        ])
        meta = _read_metadata(project_path)
        if not meta:
            meta = {"created_at": datetime.now().isoformat()}
        meta["name"] = project_name or meta.get("name", os.path.splitext(filename)[0])
        meta["page_count"] = total_pages
        _write_metadata(project_path, meta)

        logger.info(f"Uploaded PDF '{filename}' to project '{project_id}' ({len(pages)} new pages, {total_pages} total)")
        return UploadResponse(
            project_id=project_id,
            name=meta["name"],
            page_count=total_pages,
            message=f"Added {len(pages)} pages from {filename} ({total_pages} total)"
        )

    def upload_image(self, image_bytes: bytes, filename: str, project_id: str = None,
                     project_name: str = None, preserve_name: bool = False) -> UploadResponse:
        """Upload a single image. Creates new project or adds to existing.

        Args:
            preserve_name: If True, use the original filename instead of page_NNN.png.
        """
        if project_id:
            project_path = _resolve_project_path(project_id)
            if not project_path.exists():
                raise FileNotFoundError(f"Project '{project_id}' not found")
        else:
            slug = _slugify(project_name or filename)
            project_id = f"{slug}_{_random_suffix()}"
            project_path = PAGES_PATH / project_id
            project_path.mkdir(parents=True, exist_ok=True)

        thumbs_path = project_path / "thumbnails"
        thumbs_path.mkdir(exist_ok=True)

        if preserve_name:
            stem = os.path.splitext(filename)[0]
            page_path = project_path / filename
            thumb_path = thumbs_path / f"{stem}.jpg"
        else:
            page_num = self._next_page_number(project_path)
            page_path = project_path / f"page_{page_num:03d}.png"
            thumb_path = thumbs_path / f"page_{page_num:03d}.jpg"

        page_path.write_bytes(image_bytes)
        self._make_thumbnail(str(page_path), str(thumb_path))

        # Update metadata
        total_pages = len(list(project_path.glob("*.png")))
        meta = _read_metadata(project_path)
        if not meta:
            meta = {"created_at": datetime.now().isoformat()}
        meta["name"] = project_name or meta.get("name", os.path.splitext(filename)[0])
        meta["page_count"] = total_pages
        _write_metadata(project_path, meta)

        logger.info(f"Uploaded image '{filename}' to project '{project_id}'")
        return UploadResponse(
            project_id=project_id,
            name=meta["name"],
            page_count=total_pages,
            message=f"Added image {filename} ({total_pages} total pages)"
        )

    # ============== Listing ==============

    def _get_all_projects(self) -> List[ProjectInfo]:
        """Get all projects from both sources as a flat list."""
        projects: List[ProjectInfo] = []

        # 1. Uploaded projects from pages/
        if PAGES_PATH.exists():
            for project_dir in sorted(PAGES_PATH.iterdir(), reverse=True):
                if not project_dir.is_dir():
                    continue
                meta_file = project_dir / "metadata.json"
                if not meta_file.exists():
                    continue
                try:
                    meta = json.loads(meta_file.read_text())
                except Exception:
                    continue

                page_count = len([
                    p for p in project_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")
                ])
                projects.append(ProjectInfo(
                    project_id=project_dir.name,
                    name=meta.get("name", project_dir.name),
                    image_count=page_count,
                    created_at=meta.get("created_at", ""),
                    parent_id=meta.get("parent_id"),
                ))

        # 2. PDF images from Predict (yolo/pdf_images/)
        if PDF_IMAGES_PATH.exists():
            for folder in sorted(PDF_IMAGES_PATH.iterdir()):
                if not folder.is_dir():
                    continue
                page_count = len([
                    p for p in folder.iterdir()
                    if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")
                ])
                if page_count == 0:
                    continue
                pdf_meta = _read_metadata(folder)
                projects.append(ProjectInfo(
                    project_id=f"{_PDF_IMG_PREFIX}{folder.name}",
                    name=pdf_meta.get("name", folder.name),
                    image_count=page_count,
                    created_at=pdf_meta.get("created_at", ""),
                    parent_id=pdf_meta.get("parent_id"),
                ))

        return projects

    def list_projects(self) -> ProjectListResponse:
        """List all projects (flat list with parent_id info)."""
        projects = self._get_all_projects()
        # Compute children_count for each project
        parent_counts: Dict[str, int] = {}
        for p in projects:
            if p.parent_id:
                parent_counts[p.parent_id] = parent_counts.get(p.parent_id, 0) + 1
        for p in projects:
            p.children_count = parent_counts.get(p.project_id, 0)
        return ProjectListResponse(projects=projects)

    def get_tree(self) -> List[Dict]:
        """Build full project tree with nested children."""
        all_projects = self._get_all_projects()
        for p in all_projects:
            if p.parent_id:
                logger.info(f"get_tree: project '{p.name}' ({p.project_id}) has parent_id={p.parent_id!r}")

        # Index by project_id
        by_id: Dict[str, Dict] = {}
        for p in all_projects:
            by_id[p.project_id] = {
                "project_id": p.project_id,
                "name": p.name,
                "image_count": p.image_count,
                "created_at": p.created_at,
                "parent_id": p.parent_id,
                "children_count": 0,
                "total_image_count": p.image_count,
                "children": [],
            }

        # Build tree
        roots = []
        for pid, node in by_id.items():
            parent_id = node["parent_id"]
            if parent_id and parent_id in by_id:
                by_id[parent_id]["children"].append(node)
                by_id[parent_id]["children_count"] += 1
            else:
                roots.append(node)

        # Sort children by name
        def sort_children(nodes):
            nodes.sort(key=lambda n: n["name"].lower())
            for n in nodes:
                if n["children"]:
                    sort_children(n["children"])
        sort_children(roots)

        # Accumulate image counts upward
        def accumulate(node):
            total = node["image_count"]
            for child in node["children"]:
                total += accumulate(child)
            node["total_image_count"] = total
            return total

        for root in roots:
            accumulate(root)

        return roots

    def get_children(self, project_id: str) -> List[ProjectInfo]:
        """Get direct children of a project."""
        all_projects = self._get_all_projects()
        children = [p for p in all_projects if p.parent_id == project_id]
        children.sort(key=lambda p: p.name.lower())
        return children

    def get_breadcrumb(self, project_id: str) -> List[ProjectInfo]:
        """Get the path from root to this project (inclusive)."""
        all_projects = self._get_all_projects()
        by_id = {p.project_id: p for p in all_projects}

        path = []
        current_id = project_id
        visited = set()
        while current_id is not None:
            if current_id in visited:
                break
            visited.add(current_id)
            project = by_id.get(current_id)
            if not project:
                break
            path.append(project)
            current_id = project.parent_id
        path.reverse()
        return path

    def get_project(self, project_id: str) -> Optional[ProjectDetail]:
        """Get a single project with all its pages."""
        project_path = _resolve_project_path(project_id)
        if not project_path.exists():
            return None

        meta = _read_metadata(project_path)
        name = meta.get("name", project_path.name)

        pages: List[PageInfo] = []
        # Find all PNG/JPG images (exclude thumbnails dir, metadata, etc.)
        image_files = sorted(
            p for p in project_path.glob("*.png")
            if p.is_file()
        )
        # Also include jpg/jpeg
        image_files += sorted(
            p for p in project_path.glob("*.jpg")
            if p.is_file()
        )
        image_files += sorted(
            p for p in project_path.glob("*.jpeg")
            if p.is_file()
        )

        for idx, png in enumerate(image_files):
            # For page_NNN.png files, extract the number; for others use index+1
            if png.stem.startswith("page_"):
                page_num_str = png.stem.replace("page_", "").lstrip("0") or "1"
                page_num = int(page_num_str)
            else:
                page_num = idx + 1

            stat = png.stat()
            pages.append(PageInfo(
                filename=png.name,
                page_number=page_num,
                thumbnail_url=f"/pages/projects/{project_id}/file/{png.name}",
                full_url=f"/pages/projects/{project_id}/file/{png.name}",
                file_size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                file_type=png.suffix.lstrip(".").upper(),
            ))

        return ProjectDetail(
            project_id=project_id,
            name=name,
            pages=pages,
            total_pages=len(pages),
        )

    # ============== Image Retrieval ==============

    def get_file_path(self, project_id: str, filename: str) -> Optional[str]:
        """Get the filesystem path for a file by its exact filename."""
        project_path = _resolve_project_path(project_id)
        file_path = project_path / filename
        if file_path.exists() and file_path.is_file():
            return str(file_path)
        # Also check thumbnails directory
        thumb_path = project_path / "thumbnails" / filename
        if thumb_path.exists() and thumb_path.is_file():
            return str(thumb_path)
        return None

    def get_page_path(self, project_id: str, page_number: int) -> Optional[str]:
        """Get the filesystem path for a page image."""
        project_path = _resolve_project_path(project_id)
        # Try 3-digit padding (uploaded) and 4-digit padding (pdf_images from Predict)
        for fmt in [f"page_{page_number:03d}.png", f"page_{page_number:04d}.png"]:
            page_path = project_path / fmt
            if page_path.exists():
                return str(page_path)
        return None

    def get_thumbnail_path(self, project_id: str, page_number: int) -> Optional[str]:
        """Get the thumbnail path, generating it if missing."""
        project_path = _resolve_project_path(project_id)
        thumbs_dir = project_path / "thumbnails"

        # Check existing thumbnails (both 3 and 4 digit)
        for fmt in [f"page_{page_number:03d}.jpg", f"page_{page_number:04d}.jpg"]:
            thumb_path = thumbs_dir / fmt
            if thumb_path.exists():
                return str(thumb_path)

        # Generate from full image
        full_path = self.get_page_path(project_id, page_number)
        if full_path and os.path.exists(full_path):
            thumbs_dir.mkdir(parents=True, exist_ok=True)
            thumb_path = thumbs_dir / f"page_{page_number:04d}.jpg"
            self._make_thumbnail(full_path, str(thumb_path))
            return str(thumb_path)

        return None

    # ============== Delete ==============

    def delete_pages(self, project_id: str, filenames: List[str]) -> int:
        """Delete specific pages from a project by filename. Returns the number of pages deleted."""
        project_path = _resolve_project_path(project_id)
        if not project_path.exists():
            raise FileNotFoundError(f"Project '{project_id}' not found")

        deleted = 0
        for fname in filenames:
            # Sanitize: only allow the basename to prevent path traversal
            safe_name = Path(fname).name
            page_path = project_path / safe_name
            if page_path.exists() and page_path.is_file():
                page_path.unlink()
                deleted += 1
                # Also remove thumbnail (try same stem with .jpg)
                stem = Path(safe_name).stem
                for ext in [".jpg", ".jpeg", ".png"]:
                    thumb_path = project_path / "thumbnails" / f"{stem}{ext}"
                    if thumb_path.exists():
                        thumb_path.unlink()

        # Update metadata page_count
        meta = _read_metadata(project_path)
        if meta:
            meta["page_count"] = len([
                p for p in project_path.iterdir()
                if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")
            ])
            _write_metadata(project_path, meta)

        logger.info(f"Deleted {deleted} pages from project '{project_id}'")
        return deleted

    def delete_project(self, project_id: str) -> Dict:
        """Delete a project. Refuses if it has children."""
        project_path = _resolve_project_path(project_id)
        if not project_path.exists():
            return {"deleted": False, "error": "Project not found"}

        children = self.get_children(project_id)
        if children:
            return {
                "deleted": False,
                "error": f"Cannot delete: folder has {len(children)} subfolder(s). Remove them first."
            }

        shutil.rmtree(project_path)
        logger.info(f"Deleted project '{project_id}'")
        return {"deleted": True}

    # ============== Download ==============

    def download_project_zip(self, project_id: str) -> str:
        """
        Download a project as a ZIP, recursively including child projects as sub-folders.

        Structure for a project with children:
            project_name/
                child_folder_1/
                    page_001.png
                    page_002.png
                child_folder_2/
                    page_001.png
                manifest.json  (if present)

        Structure for a flat project (no children):
            project_name/
                page_001.png
                page_002.png
                manifest.json  (if present)

        Returns path to a temp zip file (caller must delete).
        """
        import zipfile
        import tempfile

        project_path = _resolve_project_path(project_id)
        if not project_path.exists():
            raise FileNotFoundError(f"Project '{project_id}' not found")

        meta = _read_metadata(project_path)
        project_name = meta.get("name", project_path.name)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix=f"{project_name}_")
        tmp.close()

        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            self._add_project_to_zip(zf, project_id, project_name)

        logger.info(f"Created download ZIP for project '{project_id}': {tmp.name}")
        return tmp.name

    def _add_project_to_zip(self, zf, project_id: str, zip_prefix: str):
        """Recursively add a project's pages and children to a ZIP."""
        import zipfile

        project_path = _resolve_project_path(project_id)
        if not project_path.exists():
            return

        # Add page images (all image files, not just page_*.png)
        image_files = sorted(
            p for p in project_path.iterdir()
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")
        )
        for img_file in image_files:
            zf.write(img_file, f"{zip_prefix}/{img_file.name}")

        # Add manifest.json if present
        manifest_path = project_path / "manifest.json"
        if manifest_path.exists():
            zf.write(manifest_path, f"{zip_prefix}/manifest.json")

        # Recurse into children (child.name already resolves metadata name with correct fallback)
        children = self.get_children(project_id)
        for child in children:
            self._add_project_to_zip(zf, child.project_id, f"{zip_prefix}/{child.name}")

    # ============== Helpers ==============

    @staticmethod
    def _make_thumbnail(image_path: str, thumb_path: str):
        """Create a 250x250 JPEG thumbnail."""
        try:
            im = Image.open(image_path)
            im.thumbnail((250, 250))
            if im.mode != "RGB":
                im = im.convert("RGB")
            os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
            im.save(thumb_path, format="JPEG")
        except Exception as e:
            logger.warning(f"Failed to create thumbnail for {image_path}: {e}")
