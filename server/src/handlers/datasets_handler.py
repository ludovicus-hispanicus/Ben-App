import math
import time
import logging
from random import randint
from typing import Dict, List, Optional

from entities.dataset import Dataset
from mongo.local_db_client import LocalDBClient as MongoClient
from mongo.mongo_collection import MongoCollection

logger = logging.getLogger(__name__)


class DatasetsHandler:
    COLLECTION_NAME = "datasets"

    def __init__(self):
        print("datasets handler called")
        self._collection = MongoClient.get_db().datasets

    def list_datasets(self, parent_id: Optional[int] = None) -> List[Dataset]:
        """List datasets, optionally filtered by parent_id.

        - parent_id=None (default): return ALL datasets (backward compatible)
        - parent_id=0: return root-level only (where parent_id is None/missing)
        - parent_id=<int>: return children of that dataset
        """
        collection = MongoCollection(
            collection_name=self.COLLECTION_NAME,
            obj_type=Dataset
        )
        if parent_id is None:
            result = collection.find_many(
                find_filter={},
                sort=[("created_at", -1)]
            )
            return result or []
        elif parent_id == 0:
            all_datasets = collection.find_many(
                find_filter={},
                sort=[("created_at", -1)]
            )
            return [d for d in (all_datasets or []) if d.parent_id is None]
        else:
            result = collection.find_many(
                find_filter={"parent_id": int(parent_id)},
                sort=[("created_at", -1)]
            )
            return result or []

    def get_dataset(self, dataset_id: int) -> Optional[Dataset]:
        collection = MongoCollection(
            collection_name=self.COLLECTION_NAME,
            obj_type=Dataset
        )
        results = collection.find_many(
            find_filter={"dataset_id": int(dataset_id)},
            limit=1
        )
        return results[0] if results else None

    def create_dataset(self, name: str, parent_id: Optional[int] = None) -> int:
        if parent_id is not None:
            parent = self.get_dataset(parent_id)
            if not parent:
                raise ValueError(f"Parent dataset {parent_id} not found")

        dataset = Dataset(
            dataset_id=randint(1000000, 9999999),
            name=name,
            created_at=math.floor(time.time()),
            parent_id=parent_id
        )
        self._collection.insert_one(dataset.dict())
        return dataset.dataset_id

    def rename_dataset(self, dataset_id: int, name: str):
        self._collection.update_one(
            {"dataset_id": int(dataset_id)},
            {"$set": {"name": name}}
        )

    def delete_dataset(self, dataset_id: int) -> Dict:
        """Delete a dataset. Refuses if it has children."""
        children = self.get_children(dataset_id)
        if children:
            return {
                "deleted": False,
                "error": f"Cannot delete: folder has {len(children)} subfolder(s). Remove them first."
            }
        self._collection.delete_one({"dataset_id": int(dataset_id)})
        return {"deleted": True}

    def get_children(self, dataset_id: int) -> List[Dataset]:
        """Get direct children of a dataset."""
        collection = MongoCollection(
            collection_name=self.COLLECTION_NAME,
            obj_type=Dataset
        )
        result = collection.find_many(
            find_filter={"parent_id": int(dataset_id)},
            sort=[("name", 1)]
        )
        return result or []

    def get_tree(self, text_counts: Optional[Dict[int, Dict]] = None) -> List[Dict]:
        """Build full dataset tree. text_counts is {dataset_id: {text_count, curated_count}}."""
        all_datasets = self.list_datasets(parent_id=None)

        by_id: Dict[int, Dict] = {}
        for d in all_datasets:
            counts = (text_counts or {}).get(d.dataset_id, {})
            by_id[d.dataset_id] = {
                "dataset_id": d.dataset_id,
                "name": d.name,
                "parent_id": d.parent_id,
                "created_at": d.created_at,
                "text_count": counts.get("text_count", 0),
                "curated_count": counts.get("curated_count", 0),
                "children_count": 0,
                "children": [],
            }

        roots = []
        for did, node in by_id.items():
            parent_id = node["parent_id"]
            if parent_id is not None and parent_id in by_id:
                by_id[parent_id]["children"].append(node)
                by_id[parent_id]["children_count"] += 1
            else:
                roots.append(node)

        def sort_children(nodes):
            nodes.sort(key=lambda n: n["name"].lower())
            for n in nodes:
                if n["children"]:
                    sort_children(n["children"])

        sort_children(roots)

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

    def get_breadcrumb(self, dataset_id: int) -> List[Dataset]:
        """Get the path from root to this dataset (inclusive)."""
        path = []
        current_id = dataset_id
        visited = set()
        while current_id is not None:
            if current_id in visited:
                break
            visited.add(current_id)
            dataset = self.get_dataset(current_id)
            if not dataset:
                break
            path.append(dataset)
            current_id = dataset.parent_id
        path.reverse()
        return path

    def move_dataset(self, dataset_id: int, new_parent_id: Optional[int]) -> Dict:
        """Move a dataset to a new parent. new_parent_id=None moves to root."""
        if new_parent_id is not None:
            parent = self.get_dataset(new_parent_id)
            if not parent:
                return {"updated": False, "error": "Target folder not found"}

            current_id = new_parent_id
            visited = set()
            while current_id is not None:
                if current_id == dataset_id:
                    return {"updated": False, "error": "Cannot move a folder into itself or its descendants"}
                if current_id in visited:
                    break
                visited.add(current_id)
                d = self.get_dataset(current_id)
                if not d:
                    break
                current_id = d.parent_id

        self._collection.update_one(
            {"dataset_id": int(dataset_id)},
            {"$set": {"parent_id": new_parent_id}}
        )
        return {"updated": True}

    def count_children(self, dataset_id: int) -> int:
        """Count direct children of a dataset."""
        return len(self.get_children(dataset_id))
