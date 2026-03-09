"""
CuRe Datasets Handler — Separate dataset management for CuRe (sign classifier).

Uses 'cure_datasets' collection, completely separate from CuReD's 'datasets' collection.
"""
import math
import time
import logging
from random import randint
from typing import List, Optional

from entities.dataset import Dataset
from mongo.local_db_client import LocalDBClient as MongoClient
from mongo.mongo_collection import MongoCollection


class CureDatasetsHandler:
    COLLECTION_NAME = "cure_datasets"

    def __init__(self):
        self._collection = MongoClient.get_db()[self.COLLECTION_NAME]

    def list_datasets(self) -> List[Dataset]:
        collection = MongoCollection(
            collection_name=self.COLLECTION_NAME,
            obj_type=Dataset
        )
        result = collection.find_many(
            find_filter={},
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

    def create_dataset(self, name: str) -> int:
        dataset = Dataset(
            dataset_id=randint(1000000, 9999999),
            name=name,
            created_at=math.floor(time.time())
        )
        self._collection.insert_one(dataset.dict())
        return dataset.dataset_id

    def rename_dataset(self, dataset_id: int, name: str):
        self._collection.update_one(
            {"dataset_id": int(dataset_id)},
            {"$set": {"name": name}}
        )

    def delete_dataset(self, dataset_id: int):
        self._collection.delete_one({"dataset_id": int(dataset_id)})


cure_datasets_handler = CureDatasetsHandler()
