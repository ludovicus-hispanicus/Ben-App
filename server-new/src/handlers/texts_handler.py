import datetime
from typing import List, Dict

import math
import time
import os
import platform

import pymongo

from api.dto.get_predictions import AmendmentStats
from api.dto.submit import SubmitDto
from api.dto.text import NewTextPreviewDto, GalleryItemDto
from entities.text import Text
from mongo.mongo_client import MongoClient, MongoCursor
from entities.text_progress import TextProgress
from mongo.mongo_collection import MongoCollection
from utils.storage_utils import StorageUtils
import logging


class TextsHandler:

    def __init__(self):
        print("text handler called")
        self.db = MongoClient.get_db()

    def insert_text(self, text: Text):
        self.db[MongoClient.TEXTS_COLLECTION].insert_one(text.dict())

    def aggregate_one(self, aggregation: List[dict]):
        result = self.db.texts.aggregate(aggregation)
        return MongoCursor.get_next(result)

    def get_text_by_aggregation(self, aggregation):
        text_dict = self.aggregate_one(aggregation=aggregation)

        if not text_dict:
            return None

        logging.info("parsing text")
        text: Text = Text.parse_obj(text_dict)
        logging.info(f"picked text {text.text_id}")
        self._set_text_in_use(text_id=text.text_id)

        return text

    def get_random_text_to_work_on(self):
        return self.get_text_by_aggregation(aggregation=[
            {"$match": {"is_fixed": False}},
            {"$sample": {"size": 1}}
        ])

    def get_by_text_id(self, text_id) -> Text:
        return self.get_text_by_aggregation(aggregation=[
            {"$match": {"text_id": int(text_id)}},
            {"$sample": {"size": 1}}
        ])

    def _set_text_in_use(self, text_id):
        seconds_from_1970 = math.floor(time.time())
        use_start_time = math.floor(seconds_from_1970)

        new_values = {"is_in_use": True, "use_start_time": use_start_time}

        self._update_text(text_id=text_id, new_values=new_values)

    def set_text_in_progress(self, text_id):
        query = {"text_id": text_id}

        new_values = {"$set": {"is_fixed": False}}

        self.db.texts.update_one(query, new_values)

    def set_text_not_in_use(self, text_id, is_fixed=False):
        query = {"text_id": text_id}

        new_values = {"$set": {"is_in_use": False, "use_start_time": -1, "is_fixed": is_fixed}}

        self.db.texts.update_one(query, new_values)

    def update_text_transliteration(self, text_id, new_transliteration: List[List[str]]):
        new_values = {"transliteration": new_transliteration}
        self._update_text(text_id=text_id, new_values=new_values)

    def _update_text(self, text_id, new_values: dict):
        query = {"text_id": text_id}
        new_values = {"$set": new_values}
        self.db.texts.update_one(query, new_values)

    def process_text_result(self, submit_dto: SubmitDto, user_id: str):
        saved_count = 0

        self._save_progress(submit_dto=submit_dto, user_id=user_id)
        self.set_text_not_in_use(text_id=submit_dto.text_id, is_fixed=submit_dto.is_fixed)
        if submit_dto.is_fixed:
            logging.info(f"Saved {saved_count} new result images")

    def _save_progress(self, submit_dto: SubmitDto, user_id: str):
        text_progress = TextProgress(items=submit_dto.items,
                                     akkademia=submit_dto.akkademia,
                                     submit_time=datetime.datetime.now().isoformat(),
                                     user_email=user_id)

        self.db.texts.update(
            {"text_id": submit_dto.text_id},
            {"$push": {'edit_history': text_progress.dict()}}
        )

    def get_text(self, text_id) -> Text:
        result = self.db.texts.find_one(filter={"text_id": int(text_id)})
        if result:
            text: Text = Text.parse_obj(result)
            return text
        return None

    def get_last_texts(self) -> List[Dict]:
        result = self.db.texts.find(filter={}).sort("_id", -1).limit(20)
        results = []
        for text_dict in result:
            text: Text = Text.parse_obj(text_dict)
            results.append(dict(uploader=text.uploader_id, text_id=text.text_id))

        return results

    def get_amendment_stats(self) -> AmendmentStats:
        completed_text_amount = self.db.texts.count_documents({"is_fixed": True})
        path = StorageUtils.get_confirmed_signs_path()

        signs_amount = -1
        if platform.system() == 'Linux':
            signs_amount_raw = os.popen(f"find {path} -type f | wc -l").read()
            print(signs_amount_raw)
            signs_amount = int(signs_amount_raw.replace("\n", ""))

        return AmendmentStats(completed_texts=completed_text_amount,
                              saved_signs=signs_amount)

    def get_random_texts(self) -> List[NewTextPreviewDto]:
        collection = MongoCollection(collection_name=MongoClient.TEXTS_COLLECTION, obj_type=Text)
        result = collection.find_many(find_filter={}, limit=50, sort=[("use_start_time", pymongo.DESCENDING)])
        return self.generate_previews(result=result)

    def get_by_symbol(self, symbol: str) -> List[NewTextPreviewDto]:
        collection = MongoCollection(collection_name=MongoClient.TEXTS_COLLECTION, obj_type=Text)
        result = collection.find_many(limit=50, find_filter={
                "edit_history": {
                    "$elemMatch": {
                        "items": {
                            "$elemMatch": {
                                "$elemMatch": {
                                    "symbol": symbol
                                }
                            }
                        }
                    }
                }
            })

        return self.generate_previews(result=result)

    @staticmethod
    def generate_previews(result: List[Text]) -> List[GalleryItemDto]:
        previews = []
        for text in result:
            try:
                previews.append(GalleryItemDto.from_text(text=text))
            except Exception as e:
                print(f"failed to load new text {text.text_id}, {e}")

        return previews
