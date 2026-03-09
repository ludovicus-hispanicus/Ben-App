import os
import json
import logging
import threading
import time
from bson import ObjectId
from typing import List, Dict, Any, Optional, Type
from pydantic import BaseModel

# Per-file locks to prevent concurrent read/write corruption
_file_locks: Dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()

def _get_file_lock(path: str) -> threading.Lock:
    with _file_locks_lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]

# ── In-memory cache shared across LocalCollection instances ──
# Keyed by absolute file path → (data list, mtime at load)
_cache: Dict[str, tuple] = {}
_cache_lock = threading.Lock()

class LocalCollection:
    def __init__(self, collection_path: str, obj_type: Optional[Type[BaseModel]] = None):
        self.path = collection_path
        self._obj_type = obj_type
        self._lock = _get_file_lock(collection_path)
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def _read_unsafe(self) -> List[Dict]:
        """Read without lock — caller must hold self._lock.
        Uses an in-memory cache; only re-reads from disk when the
        file's mtime has changed."""
        try:
            abs_path = os.path.abspath(self.path)
            mtime = os.path.getmtime(abs_path)
            with _cache_lock:
                cached = _cache.get(abs_path)
                if cached and cached[1] == mtime:
                    return cached[0]

            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            with _cache_lock:
                _cache[abs_path] = (data, mtime)
            return data
        except Exception as e:
            logging.error(f"Error reading local db {self.path}: {e}")
            return []

    def _write_unsafe(self, data: List[Dict]):
        """Write without lock — caller must hold self._lock. Uses atomic rename.
        Also updates the in-memory cache."""
        try:
            tmp_path = self.path + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)

            # Update cache immediately so subsequent reads don't hit disk
            abs_path = os.path.abspath(self.path)
            mtime = os.path.getmtime(abs_path)
            with _cache_lock:
                _cache[abs_path] = (data, mtime)
        except Exception as e:
            logging.error(f"Error writing local db {self.path}: {e}")

    def _read(self) -> List[Dict]:
        with self._lock:
            return self._read_unsafe()

    def _write(self, data: List[Dict]):
        with self._lock:
            self._write_unsafe(data)

    def insert_one(self, obj: Any):
        if isinstance(obj, BaseModel):
            item = obj.dict()
        else:
            item = dict(obj)

        # Ensure _id exists for internal reference if needed (use ObjectId for compatibility)
        if '_id' not in item:
            item['_id'] = str(ObjectId())

        with self._lock:
            data = self._read_unsafe()
            data.append(item)
            self._write_unsafe(data)
        return item

    def find_one(self, filter: Dict) -> Optional[Dict]:
        data = self._read()
        for item in data:
            match = True
            for k, v in filter.items():
                if item.get(k) != v:
                    match = False
                    break
            if match:
                return item
        return None

    def _match_elem_match(self, array: List, elem_filter: Dict) -> bool:
        """Check if any element in array matches all conditions in elem_filter."""
        if not isinstance(array, list):
            return False
        for elem in array:
            if not isinstance(elem, dict):
                continue
            match = True
            for k, v in elem_filter.items():
                if elem.get(k) != v:
                    match = False
                    break
            if match:
                return True
        return False

    def _match_filter(self, item: Dict, filter_key: str, filter_value: Any) -> bool:
        """Check if item matches a single filter condition."""
        # Handle $elemMatch for array fields
        if isinstance(filter_value, dict) and '$elemMatch' in filter_value:
            array = item.get(filter_key, [])
            return self._match_elem_match(array, filter_value['$elemMatch'])

        # Handle $in operator
        if isinstance(filter_value, dict) and '$in' in filter_value:
            return item.get(filter_key) in filter_value['$in']

        # Handle $exists operator
        if isinstance(filter_value, dict) and '$exists' in filter_value:
            exists = filter_key in item and item[filter_key] is not None
            return exists == filter_value['$exists']

        # Simple equality
        return item.get(filter_key) == filter_value

    def find_many(self, find_filter: Dict = {}, limit: int = 0, sort: List = None, **kwargs) -> List[Dict]:
        data = self._read()
        results = []
        for item in data:
            match = True
            for k, v in find_filter.items():
                if not self._match_filter(item, k, v):
                    match = False
                    break
            if match:
                results.append(item)

        # Simple sorting if provided (e.g. [("field", -1)])
        if sort:
            for field, direction in reversed(sort):
                def _sort_key(x, _f=field):
                    v = x.get(_f)
                    if v is None:
                        return (0, "")
                    if isinstance(v, (int, float)):
                        return (1, v)
                    return (2, str(v))
                results.sort(key=_sort_key, reverse=(direction == -1))

        if limit > 0:
            return results[:limit]
        return results

    def find(self, filter: Dict = {}, limit: int = 0, sort: List = None, **kwargs):
        # Mocking the cursor-like behavior for simple cases
        results = self.find_many(filter, limit=limit, sort=sort, **kwargs)
        return iter(results)

    def _get_nested_value(self, item: Dict, path: str) -> Any:
        """Get a value from a nested path like 'transliterations.transliteration_id'."""
        parts = path.split('.')
        current = item
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                # For array fields, check if any element has the field
                return [elem.get(part) for elem in current if isinstance(elem, dict)]
            else:
                return None
        return current

    def _match_query_key(self, item: Dict, key: str, value: Any) -> tuple:
        """
        Match a query key against an item, supporting dot notation for nested fields.
        Returns (matched: bool, matched_array_index: int or None).
        """
        if '.' not in key:
            return (item.get(key) == value, None)

        parts = key.split('.')
        if len(parts) == 2:
            array_field, nested_field = parts
            array = item.get(array_field, [])
            if isinstance(array, list):
                for idx, elem in enumerate(array):
                    if isinstance(elem, dict) and elem.get(nested_field) == value:
                        return (True, idx)
        return (False, None)

    def _apply_push_with_positional(self, item: Dict, push_path: str, value: Any, matched_idx: int):
        """Apply $push with positional $ operator support."""
        if '.$.' in push_path:
            # Handle positional operator: "transliterations.$.edit_history"
            parts = push_path.split('.$.')
            if len(parts) == 2:
                array_field, nested_field = parts
                array = item.get(array_field, [])
                if isinstance(array, list) and 0 <= matched_idx < len(array):
                    target = array[matched_idx]
                    if isinstance(target, dict):
                        if nested_field not in target:
                            target[nested_field] = []
                        if isinstance(target[nested_field], list):
                            target[nested_field].append(value)
                            return True
        else:
            # Simple push without positional operator
            if push_path not in item:
                item[push_path] = []
            if isinstance(item[push_path], list):
                item[push_path].append(value)
                return True
        return False

    def update_one(self, query: Dict, update: Dict):
        with self._lock:
            return self._update_one_unsafe(query, update)

    def _update_one_unsafe(self, query: Dict, update: Dict):
        data = self._read_unsafe()
        updated = False
        matched_array_idx = None

        for item in data:
            match = True
            for k, v in query.items():
                matched, idx = self._match_query_key(item, k, v)
                if not matched:
                    match = False
                    break
                if idx is not None:
                    matched_array_idx = idx

            if match:
                # Handle $set
                if "$set" in update:
                    for set_key, set_val in update["$set"].items():
                        if '.' not in set_key:
                            item[set_key] = set_val
                        else:
                            # Handle nested set (simple 2-level)
                            parts = set_key.split('.')
                            if len(parts) == 2 and parts[0] in item:
                                item[parts[0]][parts[1]] = set_val
                            else:
                                item[set_key] = set_val

                # Handle $push with positional operator support
                if "$push" in update:
                    for push_key, push_val in update["$push"].items():
                        self._apply_push_with_positional(item, push_key, push_val, matched_array_idx)

                # Handle $pull for array element removal
                if "$pull" in update:
                    for pull_key, pull_filter in update["$pull"].items():
                        if pull_key in item and isinstance(item[pull_key], list):
                            item[pull_key] = [
                                elem for elem in item[pull_key]
                                if not (isinstance(elem, dict) and all(elem.get(fk) == fv for fk, fv in pull_filter.items()))
                            ]

                # Handle direct update (no operators)
                if not any(k.startswith('$') for k in update.keys()):
                    item.update(update)

                updated = True
                break

        if updated:
            self._write_unsafe(data)
        return updated

    def update(self, query: Dict, update_doc: Dict):
        return self.update_one(query, update_doc)

    def aggregate(self, pipeline: List[Dict]):
        # Very limited aggregation mock for $match and $sample
        data = self._read()
        match_filter = {}
        sample_size = 0
        
        for stage in pipeline:
            if "$match" in stage:
                match_filter.update(stage["$match"])
            if "$sample" in stage:
                sample_size = stage["$sample"].get("size", 1)
        
        results = []
        for item in data:
            match = True
            for k, v in match_filter.items():
                if item.get(k) != v:
                    match = False
                    break
            if match:
                results.append(item)
        
        if sample_size > 0 and results:
            import random
            return iter(random.sample(results, min(sample_size, len(results))))
        
        return iter(results)

    def count_documents(self, filter: Dict) -> int:
        return len(self.find_many(filter))

    def distinct(self, field: str, filter: Dict = {}) -> List[Any]:
        data = self.find_many(filter)
        values = set()
        for item in data:
            if field in item:
                values.add(item[field])
        return list(values)

    def delete_one(self, filter: Dict) -> bool:
        """Delete the first document matching the filter."""
        with self._lock:
            data = self._read_unsafe()
            for i, item in enumerate(data):
                match = True
                for k, v in filter.items():
                    matched, _ = self._match_query_key(item, k, v)
                    if not matched:
                        match = False
                        break
                if match:
                    del data[i]
                    self._write_unsafe(data)
                    return True
        return False

    def drop(self):
        if os.path.exists(self.path):
            os.remove(self.path)
        self._ensure_dir()

class LocalDBClient:
    STORAGE_DIR = os.path.join(os.getcwd(), "data", "db")
    
    TEXTS_COLLECTION = "texts"
    NEW_TEXTS_COLLECTION = "new_texts"
    OCR_CORRECTIONS_COLLECTION = "ocr_corrections"
    
    _instance = None

    def __init__(self):
        os.makedirs(self.STORAGE_DIR, exist_ok=True)

    @classmethod
    def get_db(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __getitem__(self, name):
        return LocalCollection(os.path.join(self.STORAGE_DIR, f"{name}.json"))

    def __getattr__(self, name):
        return self[name]

    def list_collection_names(self):
        if not os.path.exists(self.STORAGE_DIR):
            return []
        return [f.replace(".json", "") for f in os.listdir(self.STORAGE_DIR) if f.endswith(".json")]

class MongoClient:
    """Mock for backward compatibility"""
    TEXTS_COLLECTION = "texts"
    NEW_TEXTS_COLLECTION = "new_texts"
    USERS_COLLECTION = "users"

    @staticmethod
    def get_db():
        return LocalDBClient.get_db()

class MongoCursor:
    @staticmethod
    def get_next(cursor):
        try:
            return next(cursor)
        except StopIteration:
            return None
