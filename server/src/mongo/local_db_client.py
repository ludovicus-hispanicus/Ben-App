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

class ShardedCollection:
    """Collection sharded across per-dataset JSON files.

    Storage layout:
        base_dir/
            {dataset_id}.json   — texts for each dataset
            unassigned.json     — texts with dataset_id=None
        index_path              — { text_id_str: dataset_id_or_null }

    Presents the same interface as LocalCollection so the handler
    can use it as a drop-in replacement.
    """

    UNASSIGNED = "unassigned"

    def __init__(self, base_dir: str, index_path: str, stats_path: str = None):
        self._base_dir = base_dir
        self._index_path = index_path
        self._stats_path = stats_path or os.path.join(os.path.dirname(index_path), "dataset_stats.json")
        self._index_lock = _get_file_lock(index_path)
        self._stats_lock = _get_file_lock(self._stats_path)
        os.makedirs(base_dir, exist_ok=True)
        self._index: Dict[str, Any] = self._load_index()
        self._stats: Dict[str, Dict[str, int]] = self._load_or_rebuild_stats()
        # Cache of LocalCollection instances keyed by shard filename
        self._shards: Dict[str, LocalCollection] = {}

    # ── Index management ──

    def _load_index(self) -> Dict[str, Any]:
        if not os.path.exists(self._index_path):
            return {}
        try:
            with open(self._index_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_index(self):
        tmp = self._index_path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self._index, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._index_path)

    # ── Stats cache management ──

    def _load_or_rebuild_stats(self) -> Dict[str, Dict[str, int]]:
        """Load cached stats from disk, or rebuild from shards if missing."""
        if os.path.exists(self._stats_path):
            try:
                with open(self._stats_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return self._rebuild_stats()

    @staticmethod
    def _is_text_curated(item: Dict) -> tuple:
        """Compute (is_curated, lines_count) from raw text dict.
        Mirrors NewTextPreviewDto.from_new_text logic."""
        transliterations = item.get("transliterations", [])
        if not transliterations:
            return False, 0
        is_curated_kraken = False
        is_curated_vlm = False
        lines_count = 0
        latest_trans = transliterations[-1]
        edit_history = latest_trans.get("edit_history", [])
        if edit_history:
            lines_count = len(edit_history[-1].get("lines", []))
        for trans in transliterations:
            eh = trans.get("edit_history", [])
            if eh:
                latest_edit = eh[-1]
                if latest_edit.get("is_curated_kraken", False):
                    is_curated_kraken = True
                if latest_edit.get("is_curated_vlm", False):
                    is_curated_vlm = True
                if not is_curated_kraken and not is_curated_vlm and latest_edit.get("is_fixed", False):
                    targets = latest_edit.get("training_targets") or []
                    if "kraken" in targets:
                        is_curated_kraken = True
                    if "vlm" in targets:
                        is_curated_vlm = True
                    if not targets:
                        is_curated_kraken = True
                        is_curated_vlm = True
        is_curated = is_curated_kraken or is_curated_vlm
        return is_curated, lines_count

    def _rebuild_stats(self) -> Dict[str, Dict[str, int]]:
        """Full rebuild of stats from all shard files."""
        logging.info("ShardedCollection: rebuilding dataset_stats.json from shards")
        stats: Dict[str, Dict[str, int]] = {}
        for key in self._all_shard_keys():
            if key == self.UNASSIGNED:
                continue
            path = self._shard_path(key)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue
            count = len(data)
            curated_count = 0
            curated_lines = 0
            for item in data:
                is_curated, lc = self._is_text_curated(item)
                if is_curated:
                    curated_count += 1
                    curated_lines += lc
            stats[key] = {
                "count": count,
                "curated_count": curated_count,
                "curated_lines": curated_lines,
            }
        self._save_stats(stats)
        return stats

    def _save_stats(self, stats: Dict[str, Dict[str, int]] = None):
        """Persist stats cache to disk."""
        if stats is None:
            stats = self._stats
        with self._stats_lock:
            tmp = self._stats_path + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._stats_path)

    def _ensure_stats_key(self, dataset_id) -> str:
        """Ensure a stats entry exists for this dataset and return the key."""
        key = self._shard_key(dataset_id)
        if key != self.UNASSIGNED and key not in self._stats:
            self._stats[key] = {"count": 0, "curated_count": 0, "curated_lines": 0}
        return key

    def _shard_key(self, dataset_id) -> str:
        if dataset_id is None:
            return self.UNASSIGNED
        return str(dataset_id)

    def _shard_path(self, key: str) -> str:
        return os.path.join(self._base_dir, f"{key}.json")

    def _get_shard(self, key: str) -> LocalCollection:
        if key not in self._shards:
            self._shards[key] = LocalCollection(self._shard_path(key))
        return self._shards[key]

    def _get_shard_for_text(self, text_id: int) -> Optional[LocalCollection]:
        tid = str(text_id)
        if tid not in self._index:
            return None
        dataset_id = self._index[tid]
        return self._get_shard(self._shard_key(dataset_id))

    def _all_shard_keys(self) -> List[str]:
        """List all shard keys that have data files."""
        keys = []
        if os.path.isdir(self._base_dir):
            for fname in os.listdir(self._base_dir):
                if fname.endswith('.json'):
                    keys.append(fname[:-5])
        return keys

    # ── LocalCollection-compatible interface ──

    def find_one(self, filter: Dict) -> Optional[Dict]:
        # Fast path: lookup by text_id
        if 'text_id' in filter and len(filter) == 1:
            shard = self._get_shard_for_text(int(filter['text_id']))
            if shard is None:
                return None
            return shard.find_one(filter)

        # Slow path: scan all shards
        for key in self._all_shard_keys():
            result = self._get_shard(key).find_one(filter)
            if result is not None:
                return result
        return None

    def find_many(self, find_filter: Dict = {}, limit: int = 0, sort: List = None, **kwargs) -> List[Dict]:
        # Fast path: filter by dataset_id
        if 'dataset_id' in find_filter:
            did = find_filter['dataset_id']
            key = self._shard_key(did)
            shard = self._get_shard(key)
            # Remove dataset_id from filter since all items in this shard share it
            remaining_filter = {k: v for k, v in find_filter.items() if k != 'dataset_id'}
            return shard.find_many(remaining_filter, limit=limit, sort=sort, **kwargs)

        # All shards
        all_results = []
        for key in self._all_shard_keys():
            shard = self._get_shard(key)
            all_results.extend(shard.find_many(find_filter, **kwargs))

        # Sort merged results
        if sort:
            for field, direction in reversed(sort):
                def _sort_key(x, _f=field):
                    v = x.get(_f)
                    if v is None:
                        return (0, "")
                    if isinstance(v, (int, float)):
                        return (1, v)
                    return (2, str(v))
                all_results.sort(key=_sort_key, reverse=(direction == -1))

        if limit > 0:
            return all_results[:limit]
        return all_results

    def find(self, filter: Dict = {}, limit: int = 0, sort: List = None, **kwargs):
        return iter(self.find_many(filter, limit=limit, sort=sort, **kwargs))

    def insert_one(self, obj: Any):
        if isinstance(obj, BaseModel):
            item = obj.dict()
        else:
            item = dict(obj)

        if '_id' not in item:
            item['_id'] = str(ObjectId())

        dataset_id = item.get('dataset_id')
        key = self._shard_key(dataset_id)
        shard = self._get_shard(key)

        with shard._lock:
            data = shard._read_unsafe()
            data.append(item)
            shard._write_unsafe(data)

        # Update index
        text_id = item.get('text_id')
        if text_id is not None:
            with self._index_lock:
                self._index[str(text_id)] = dataset_id
                self._save_index()

        # Update stats
        if key != self.UNASSIGNED:
            self._ensure_stats_key(dataset_id)
            self._stats[key]["count"] += 1
            is_curated, lc = self._is_text_curated(item)
            if is_curated:
                self._stats[key]["curated_count"] += 1
                self._stats[key]["curated_lines"] += lc
            self._save_stats()

        return item

    def update_one(self, query: Dict, update: Dict):
        # Fast path: by text_id
        if 'text_id' in query:
            shard = self._get_shard_for_text(int(query['text_id']))
            if shard is not None:
                result = shard.update_one(query, update)
                # If dataset_id was changed via $set, update the index
                if result and "$set" in update and "dataset_id" in update["$set"]:
                    new_did = update["$set"]["dataset_id"]
                    self._move_text_after_update(int(query['text_id']), new_did, shard)
                return result

        # Dot-notation query (e.g. "transliterations.transliteration_id": 123)
        # Need to find which shard has the matching text
        for key in self._all_shard_keys():
            shard = self._get_shard(key)
            result = shard.update_one(query, update)
            if result:
                return result
        return False

    def _move_text_after_update(self, text_id: int, new_dataset_id, old_shard: LocalCollection):
        """After dataset_id was changed via $set, move the document to the correct shard."""
        tid = str(text_id)
        old_did = self._index.get(tid)
        new_key = self._shard_key(new_dataset_id)
        old_key = self._shard_key(old_did)

        if new_key == old_key:
            # Same shard, just update index
            with self._index_lock:
                self._index[tid] = new_dataset_id
                self._save_index()
            return

        # Read from old shard, remove, write to new shard
        with old_shard._lock:
            data = old_shard._read_unsafe()
            item = None
            for i, d in enumerate(data):
                if d.get('text_id') == text_id:
                    item = data.pop(i)
                    break
            if item:
                old_shard._write_unsafe(data)

        if item:
            item['dataset_id'] = new_dataset_id
            new_shard = self._get_shard(new_key)
            with new_shard._lock:
                new_data = new_shard._read_unsafe()
                new_data.append(item)
                new_shard._write_unsafe(new_data)

        with self._index_lock:
            self._index[tid] = new_dataset_id
            self._save_index()

        # Update stats for both old and new datasets
        if item:
            is_curated, lines = self._is_text_curated(item)
            if old_key != self.UNASSIGNED and old_key in self._stats:
                self._stats[old_key]["count"] = max(0, self._stats[old_key]["count"] - 1)
                if is_curated:
                    self._stats[old_key]["curated_count"] = max(0, self._stats[old_key]["curated_count"] - 1)
                    self._stats[old_key]["curated_lines"] = max(0, self._stats[old_key]["curated_lines"] - lines)
            if new_key != self.UNASSIGNED:
                self._ensure_stats_key(new_dataset_id)
                self._stats[new_key]["count"] += 1
                if is_curated:
                    self._stats[new_key]["curated_count"] += 1
                    self._stats[new_key]["curated_lines"] += lines
            self._save_stats()

    def move_text(self, text_id: int, new_dataset_id):
        """Move a text to a different dataset (or unassigned if new_dataset_id=None)."""
        tid = str(text_id)
        old_did = self._index.get(tid)
        old_key = self._shard_key(old_did)
        new_key = self._shard_key(new_dataset_id)

        if old_key == new_key:
            return

        old_shard = self._get_shard(old_key)
        new_shard = self._get_shard(new_key)

        # Remove from old
        item = None
        with old_shard._lock:
            data = old_shard._read_unsafe()
            for i, d in enumerate(data):
                if d.get('text_id') == int(text_id):
                    item = data.pop(i)
                    break
            if item:
                old_shard._write_unsafe(data)

        # Add to new
        if item:
            item['dataset_id'] = new_dataset_id
            with new_shard._lock:
                new_data = new_shard._read_unsafe()
                new_data.append(item)
                new_shard._write_unsafe(new_data)

        # Update index
        with self._index_lock:
            self._index[tid] = new_dataset_id
            self._save_index()

        # Update stats for both old and new datasets
        if item:
            is_curated, lines = self._is_text_curated(item)
            # Decrement old
            if old_key != self.UNASSIGNED and old_key in self._stats:
                self._stats[old_key]["count"] = max(0, self._stats[old_key]["count"] - 1)
                if is_curated:
                    self._stats[old_key]["curated_count"] = max(0, self._stats[old_key]["curated_count"] - 1)
                    self._stats[old_key]["curated_lines"] = max(0, self._stats[old_key]["curated_lines"] - lines)
            # Increment new
            if new_key != self.UNASSIGNED:
                self._ensure_stats_key(new_dataset_id)
                self._stats[new_key]["count"] += 1
                if is_curated:
                    self._stats[new_key]["curated_count"] += 1
                    self._stats[new_key]["curated_lines"] += lines
            self._save_stats()

    def delete_one(self, filter: Dict) -> bool:
        # Fast path: by text_id
        if 'text_id' in filter:
            tid = int(filter['text_id'])
            tid_str = str(tid)
            dataset_id = self._index.get(tid_str)
            shard = self._get_shard_for_text(tid)
            if shard is not None:
                # Read the item before deleting for stats
                item = shard.find_one(filter)
                result = shard.delete_one(filter)
                if result:
                    with self._index_lock:
                        self._index.pop(tid_str, None)
                        self._save_index()
                    # Update stats
                    key = self._shard_key(dataset_id)
                    if key != self.UNASSIGNED and key in self._stats:
                        self._stats[key]["count"] = max(0, self._stats[key]["count"] - 1)
                        if item:
                            is_curated, lc = self._is_text_curated(item)
                            if is_curated:
                                self._stats[key]["curated_count"] = max(0, self._stats[key]["curated_count"] - 1)
                                self._stats[key]["curated_lines"] = max(0, self._stats[key]["curated_lines"] - lc)
                        self._save_stats()
                return result
            return False

        # Slow path
        for key in self._all_shard_keys():
            shard = self._get_shard(key)
            result = shard.delete_one(filter)
            if result:
                return result
        return False

    def count_documents(self, filter: Dict) -> int:
        return len(self.find_many(filter))

    def distinct(self, field: str, filter: Dict = {}) -> List[Any]:
        data = self.find_many(filter)
        values = set()
        for item in data:
            if field in item:
                values.add(item[field])
        return list(values)

    def aggregate(self, pipeline: List[Dict]):
        # Collect from all shards then apply pipeline
        all_data = []
        for key in self._all_shard_keys():
            all_data.extend(self._get_shard(key)._read())

        match_filter = {}
        sample_size = 0
        for stage in pipeline:
            if "$match" in stage:
                match_filter.update(stage["$match"])
            if "$sample" in stage:
                sample_size = stage["$sample"].get("size", 1)

        results = []
        for item in all_data:
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

    # ── Stats (lightweight) ──

    def update_stats_for_curation(self, dataset_id, curated: bool, lines_count: int):
        """Incrementally update stats when a text's curation status changes."""
        key = self._shard_key(dataset_id)
        if key == self.UNASSIGNED:
            return
        self._ensure_stats_key(dataset_id)
        if curated:
            self._stats[key]["curated_count"] += 1
            self._stats[key]["curated_lines"] += lines_count
        else:
            self._stats[key]["curated_count"] = max(0, self._stats[key]["curated_count"] - 1)
            self._stats[key]["curated_lines"] = max(0, self._stats[key]["curated_lines"] - lines_count)
        self._save_stats()

    def rebuild_stats(self):
        """Force a full rebuild of the stats cache from shard files."""
        self._stats = self._rebuild_stats()

    def get_stats_per_dataset(self) -> Dict[str, Dict[str, int]]:
        """Return precomputed per-dataset stats (O(1) — just returns cached dict).

        Returns {dataset_id_str: {"count": N, "curated_count": N, "curated_lines": N}}
        """
        return dict(self._stats)

    # ── Migration ──

    @staticmethod
    def migrate_from_single_file(source_path: str, base_dir: str, index_path: str):
        """Split a single new_texts.json into per-dataset files + index."""
        if not os.path.exists(source_path):
            logging.warning(f"ShardedCollection: source {source_path} not found")
            return

        logging.info(f"ShardedCollection: migrating {source_path} → {base_dir}")
        with open(source_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Group by dataset_id
        groups: Dict[str, List[Dict]] = {}
        index: Dict[str, Any] = {}
        for record in data:
            did = record.get('dataset_id')
            key = "unassigned" if did is None else str(did)
            groups.setdefault(key, []).append(record)
            tid = record.get('text_id')
            if tid is not None:
                index[str(tid)] = did

        os.makedirs(base_dir, exist_ok=True)

        # Write each group
        for key, records in groups.items():
            path = os.path.join(base_dir, f"{key}.json")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)

        # Write index
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False)

        # Backup original
        backup = source_path + ".bak"
        os.rename(source_path, backup)
        logging.info(f"ShardedCollection: migration complete. {len(data)} texts → {len(groups)} shards. Backup: {backup}")


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
