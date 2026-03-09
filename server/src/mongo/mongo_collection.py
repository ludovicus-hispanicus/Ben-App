from __future__ import annotations

import logging
from typing import List, Dict, Type

from pydantic import BaseModel
from pymongo.results import DeleteResult

from mongo.mongo_client import MongoClient, MongoCursor
from entities.new_text import DbModel


class MongoCollection:

    def __init__(self, collection_name: str, obj_type: Type[BaseModel]):
        self._collection = MongoClient.get_db()[collection_name]
        self._obj_type = obj_type

    def insert_one(self, obj: DbModel) -> None:
        self._collection.insert_one(obj.dict())

    def delete_one(self, filter: Dict):
        result: DeleteResult = self._collection.delete_one(filter=filter)

        if result.deleted_count != 1:
            raise Exception("Failed to delete")

    def _parse_result(self, result: Dict | None) -> BaseModel | None:
        if not result:
            return None

        obj = self._obj_type.parse_obj(result)

        return obj

    def _parse_results(self, results: List[Dict] | None) -> List[BaseModel] | None:
        if not results:
            return None

        return [self._parse_result(result=result) for result in results]

    def aggregate_one(self, aggregation: List[Dict]):
        result = self._collection.aggregate(aggregation)

        return MongoCursor.get_next(result)

    def find_one(self, find_filter: Dict) -> BaseModel | None:
        result = self._collection.find_one(filter=find_filter)

        return self._parse_result(result=result)

    def find_many(self, find_filter: Dict, **kwargs) -> List[BaseModel] | None:
        logging.info(f"filter {find_filter},kwars {kwargs}")
        results = self._collection.find(filter=find_filter, **kwargs)

        return self._parse_results(results=results)

    def get_one_by_aggregation(self, aggregation) -> BaseModel | None:
        obj_dict = self.aggregate_one(aggregation=aggregation)

        return self._parse_result(result=obj_dict)

    def update_one(self, query: Dict, new_values: Dict) -> None:
        set_values = {"$set": new_values}

        self._collection.update_one(query, set_values)

    def count(self) -> int:
        return self._collection.count_documents({})
