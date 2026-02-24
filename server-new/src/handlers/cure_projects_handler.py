"""
CuRe Projects Handler — Separate project management for CuRe (sign classifier).

Uses 'cure_projects' collection, completely separate from CuReD's 'projects' collection.
"""
import math
import time
import logging
from random import randint
from typing import List, Optional

from entities.project import Project
from mongo.local_db_client import LocalDBClient as MongoClient
from mongo.mongo_collection import MongoCollection


class CureProjectsHandler:
    COLLECTION_NAME = "cure_projects"

    def __init__(self):
        self._collection = MongoClient.get_db()[self.COLLECTION_NAME]

    def list_projects(self) -> List[Project]:
        collection = MongoCollection(
            collection_name=self.COLLECTION_NAME,
            obj_type=Project
        )
        result = collection.find_many(
            find_filter={},
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

    def create_project(self, name: str) -> int:
        project = Project(
            project_id=randint(1000000, 9999999),
            name=name,
            created_at=math.floor(time.time())
        )
        self._collection.insert_one(project.dict())
        return project.project_id

    def rename_project(self, project_id: int, name: str):
        self._collection.update_one(
            {"project_id": int(project_id)},
            {"$set": {"name": name}}
        )

    def delete_project(self, project_id: int):
        self._collection.delete_one({"project_id": int(project_id)})


cure_projects_handler = CureProjectsHandler()
