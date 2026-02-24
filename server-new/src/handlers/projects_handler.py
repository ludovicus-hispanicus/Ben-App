import math
import time
import logging
from random import randint
from typing import Dict, List, Optional

from entities.project import Project
from mongo.local_db_client import LocalDBClient as MongoClient
from mongo.mongo_collection import MongoCollection

logger = logging.getLogger(__name__)


class ProjectsHandler:
    COLLECTION_NAME = "projects"

    def __init__(self):
        print("projects handler called")
        self._collection = MongoClient.get_db().projects

    def list_projects(self, parent_id: Optional[int] = None) -> List[Project]:
        """List projects, optionally filtered by parent_id.

        - parent_id=None (default): return ALL projects (backward compatible)
        - parent_id=0: return root-level only (where parent_id is None/missing)
        - parent_id=<int>: return children of that project
        """
        collection = MongoCollection(
            collection_name=self.COLLECTION_NAME,
            obj_type=Project
        )
        if parent_id is None:
            # Return all projects
            result = collection.find_many(
                find_filter={},
                sort=[("created_at", -1)]
            )
            return result or []
        elif parent_id == 0:
            # Return root-level projects (parent_id is None or missing)
            all_projects = collection.find_many(
                find_filter={},
                sort=[("created_at", -1)]
            )
            return [p for p in (all_projects or []) if p.parent_id is None]
        else:
            # Return children of specific project
            result = collection.find_many(
                find_filter={"parent_id": int(parent_id)},
                sort=[("created_at", -1)]
            )
            return result or []

    def get_project(self, project_id: int) -> Optional[Project]:
        collection = MongoCollection(
            collection_name=self.COLLECTION_NAME,
            obj_type=Project
        )
        results = collection.find_many(
            find_filter={"project_id": int(project_id)},
            limit=1
        )
        return results[0] if results else None

    def create_project(self, name: str, parent_id: Optional[int] = None) -> int:
        if parent_id is not None:
            parent = self.get_project(parent_id)
            if not parent:
                raise ValueError(f"Parent project {parent_id} not found")

        project = Project(
            project_id=randint(1000000, 9999999),
            name=name,
            created_at=math.floor(time.time()),
            parent_id=parent_id
        )
        self._collection.insert_one(project.dict())
        return project.project_id

    def rename_project(self, project_id: int, name: str):
        self._collection.update_one(
            {"project_id": int(project_id)},
            {"$set": {"name": name}}
        )

    def delete_project(self, project_id: int) -> Dict:
        """Delete a project. Refuses if it has children."""
        children = self.get_children(project_id)
        if children:
            return {
                "deleted": False,
                "error": f"Cannot delete: folder has {len(children)} subfolder(s). Remove them first."
            }
        self._collection.delete_one({"project_id": int(project_id)})
        return {"deleted": True}

    def get_children(self, project_id: int) -> List[Project]:
        """Get direct children of a project."""
        collection = MongoCollection(
            collection_name=self.COLLECTION_NAME,
            obj_type=Project
        )
        result = collection.find_many(
            find_filter={"parent_id": int(project_id)},
            sort=[("name", 1)]
        )
        return result or []

    def get_tree(self, text_counts: Optional[Dict[int, Dict]] = None) -> List[Dict]:
        """Build full project tree. text_counts is {project_id: {text_count, curated_count}}."""
        all_projects = self.list_projects(parent_id=None)

        # Index by project_id
        by_id: Dict[int, Dict] = {}
        for p in all_projects:
            counts = (text_counts or {}).get(p.project_id, {})
            by_id[p.project_id] = {
                "project_id": p.project_id,
                "name": p.name,
                "parent_id": p.parent_id,
                "created_at": p.created_at,
                "text_count": counts.get("text_count", 0),
                "curated_count": counts.get("curated_count", 0),
                "children_count": 0,
                "children": [],
            }

        # Build tree by attaching children to parents
        roots = []
        for pid, node in by_id.items():
            parent_id = node["parent_id"]
            if parent_id is not None and parent_id in by_id:
                by_id[parent_id]["children"].append(node)
                by_id[parent_id]["children_count"] += 1
            else:
                roots.append(node)

        # Sort children by name at each level
        def sort_children(nodes):
            nodes.sort(key=lambda n: n["name"].lower())
            for n in nodes:
                if n["children"]:
                    sort_children(n["children"])

        sort_children(roots)

        # Accumulate text counts upward (children counts bubble to parents)
        def accumulate(node):
            total_texts = node["text_count"]
            total_curated = node["curated_count"]
            for child in node["children"]:
                ct, cc = accumulate(child)
                total_texts += ct
                total_curated += cc
            node["total_text_count"] = total_texts
            node["total_curated_count"] = total_curated
            return total_texts, total_curated

        for root in roots:
            accumulate(root)

        return roots

    def get_breadcrumb(self, project_id: int) -> List[Project]:
        """Get the path from root to this project (inclusive)."""
        path = []
        current_id = project_id
        visited = set()
        while current_id is not None:
            if current_id in visited:
                break
            visited.add(current_id)
            project = self.get_project(current_id)
            if not project:
                break
            path.append(project)
            current_id = project.parent_id
        path.reverse()
        return path

    def move_project(self, project_id: int, new_parent_id: Optional[int]) -> Dict:
        """Move a project to a new parent. new_parent_id=None moves to root."""
        if new_parent_id is not None:
            # Verify target exists
            parent = self.get_project(new_parent_id)
            if not parent:
                return {"updated": False, "error": "Target folder not found"}

            # Cycle detection: walk from new_parent upward, ensure we don't hit project_id
            current_id = new_parent_id
            visited = set()
            while current_id is not None:
                if current_id == project_id:
                    return {"updated": False, "error": "Cannot move a folder into itself or its descendants"}
                if current_id in visited:
                    break
                visited.add(current_id)
                p = self.get_project(current_id)
                if not p:
                    break
                current_id = p.parent_id

        self._collection.update_one(
            {"project_id": int(project_id)},
            {"$set": {"parent_id": new_parent_id}}
        )
        return {"updated": True}

    def count_children(self, project_id: int) -> int:
        """Count direct children of a project."""
        return len(self.get_children(project_id))
