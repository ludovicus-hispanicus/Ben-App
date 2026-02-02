import datetime
from random import randint
from typing import List, Dict

import math
import time
import os
import platform

import pymongo

from api.dto.get_predictions import AmendmentStats
from api.dto.submissions import TransliterationSubmissionPreview, TextIdentifiersDto, TransliterationSubmitDto
from api.dto.submit import SubmitDto
from api.dto.text import NewTextPreviewDto, GalleryItemDto
from entities.new_text import NewText, TransliterationSubmission, TransliterationEdit, TransliterationSource
from entities.text import Uploader
from mongo.mongo_client import MongoClient, MongoCursor
from entities.text_progress import TextProgress
from mongo.mongo_collection import MongoCollection
from utils.storage_utils import StorageUtils
import logging


class NewTextsHandler:
    COLLECTION_NAME = "new_texts"

    def __init__(self):
        print("new text handler called")
        self._collection = MongoClient.get_db().new_texts
        self._load_museums()

    def _load_museums(self):
        self.museums = []
        with open(StorageUtils.get_museums_file_path(), encoding="utf-8") as new_csv:
            for line in new_csv.readlines():
                items = line.split(",", 1)
                museum_name = items[0]
                description = items[1].replace("\"", "")
                museum = f"{museum_name} - {description}"
                self.museums.append(museum)

    # def _load_publications(self):
    #     self.publications = []
    #     with open(StorageUtils.get_classes_file_path(), encoding="utf-8") as new_csv:
    #         for line in new_csv.readlines():
    #             items = line.split(",")
    #             museum_name = items[0]
    #             description = items[1].replace("\"", "")
    #             self.publications[museum_name] = description

    def insert_text(self, text: NewText):
        self._collection.insert_one(text.dict())

    def aggregate_one(self, aggregation: List[dict]):
        result = self._collection.aggregate(aggregation)
        return MongoCursor.get_next(result)

    def get_text_by_aggregation(self, aggregation):
        text_dict = self.aggregate_one(aggregation=aggregation)

        if not text_dict:
            return None

        logging.info("parsing text")
        text: NewText = NewText.parse_obj(text_dict)
        logging.info(f"picked text {text.text_id}")
        # self._set_text_in_use(text_id=text.text_id)

        return text

    def get_random_text_to_work_on(self):
        return self.get_text_by_aggregation(aggregation=[
            {"$match": {"is_fixed": False}},
            {"$sample": {"size": 1}}
        ])

    def get_by_text_id(self, text_id) -> NewText:
        return self.get_text_by_aggregation(aggregation=[
            {"$match": {"text_id": int(text_id)}},
            {"$sample": {"size": 1}}
        ])

    def get_text_cured_transliterations(self, text_id) -> List[TransliterationSubmission]:
        text: NewText = self.get_by_text_id(text_id=text_id)
        cured_transliterations = [trans for trans in text.transliterations
                                  if trans.source == TransliterationSource.CURED.value]
        return cured_transliterations

    def get_text_cured_transliterations_preview(self, text_id) -> List[TransliterationSubmissionPreview]:
        cured_transliterations = self.get_text_cured_transliterations(text_id=text_id)

        previews = [TransliterationSubmissionPreview.from_transliteration_entity(trans)
                    for trans in cured_transliterations]

        return previews

    def list_texts(self) -> List[NewTextPreviewDto]:
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)
        result = collection.find_many(find_filter={}, limit=1000, sort=[("use_start_time", pymongo.DESCENDING)])
        previews = [NewTextPreviewDto.from_new_text(new_text=new_text) for new_text in result]

        return previews

    def get_random_texts(self) -> List[NewTextPreviewDto]:
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)
        result = collection.find_many(find_filter={}, limit=50, sort=[("use_start_time", pymongo.DESCENDING)])
        return self.generate_previews(result=result)

    def get_by_symbol(self, symbol: str) -> List[NewTextPreviewDto]:
        # NewText has list of TransliterationSubmission each contains list of TransliterationEdit,
        # each contains list of string lines. find texts that contain the symbol in any of the lines
        # and return the text
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)
        result = collection.find_many(limit=100, find_filter={
            "transliterations": {
                "$elemMatch": {
                    "edit_history": {
                        "$elemMatch": {
                            "lines": {
                                "$elemMatch": {
                                    "$regex": symbol
                                }
                            }
                        }
                    }
                }
            }
        })

        return self.generate_previews(result=result)

    @staticmethod
    def generate_previews(result: List[NewText]):
        previews = []
        for new_text in result:
            try:
                previews.append(GalleryItemDto.from_new_text(new_text=new_text))
            except Exception as e:
                print(f"failed to load new text {new_text.text_id}, {e}")

        return previews

    def get_by_text_identifiers_dto(self, text_identifiers: TextIdentifiersDto) -> NewText:
        query_items = text_identifiers.to_query_items()
        print(query_items)

        # Return None if no valid query items (MongoDB $or requires non-empty array)
        if not query_items:
            return None

        result = self._collection.find({
            "$or": query_items
        })

        text_dict = MongoCursor.get_next(result)
        if not text_dict:
            return None

        logging.info("parsing text")
        text: NewText = NewText.parse_obj(text_dict)

        return text

    def _set_text_in_use(self, text_id):
        use_start_time = self._get_time_in_numbers()

        new_values = {"is_in_use": True, "use_start_time": use_start_time}

        self._update_text(text_id=text_id, new_values=new_values)

    def _update_text_use_time(self, text_id):
        use_start_time = self._get_time_in_numbers()
        new_values = {"use_start_time": use_start_time}

        self._update_text(text_id=text_id, new_values=new_values)

    def _get_time_in_numbers(self):
        seconds_from_1970 = math.floor(time.time())
        return math.floor(seconds_from_1970)

    def set_text_not_in_use(self, text_id, is_fixed=False):
        query = {"text_id": text_id}

        new_values = {"$set": {"is_in_use": False, "use_start_time": -1, "is_fixed": is_fixed}}

        self._collection.update_one(query, new_values)

    def update_text_transliteration(self, text_id, new_transliteration: List[List[str]]):
        new_values = {"transliteration": new_transliteration}
        self._update_text(text_id=text_id, new_values=new_values)

    def _update_text(self, text_id, new_values: dict):
        query = {"text_id": text_id}
        new_values = {"$set": new_values}
        self._collection.update_one(query, new_values)

    def save_new_transliteration(self, dto: TransliterationSubmitDto, uploader_id: str):
        transliteration_id = dto.transliteration_id or self._create_new_transliteration(dto=dto,
                                                                                        uploader_id=uploader_id,
                                                                                        text_id=dto.text_id)
        transliteration_edit = TransliterationEdit(
            lines=dto.lines,
            boxes=dto.boxes,
            user_id=uploader_id,
            time=datetime.datetime.now().isoformat(),
            is_fixed=dto.is_fixed
        )
        self.save_transliteration_edit(text_id=dto.text_id, transliteration_id=transliteration_id,
                                       transliteration_edit=transliteration_edit)
        logging.info(f"Done saving new transliteration for transliteration id {transliteration_id}")
        return transliteration_id

    def save_transliteration_edit(self, text_id: int, transliteration_id: int,
                                  transliteration_edit: TransliterationEdit):
        a = self._collection.update_one(
            {"text_id": text_id, "transliterations.transliteration_id": transliteration_id},  # is it tho?
            {"$push": {'transliterations.$.edit_history': transliteration_edit.dict()}}
        )
        self._update_text_use_time(text_id=text_id)

    def create_new_text(self, identifiers: TextIdentifiersDto, metadata: List[Dict], uploader_id: str) -> int:
        new_text = NewText(
            text_id=randint(1000000, 9999999),
            publication_id=identifiers.publication.get_value() if identifiers.publication else None,
            museum_id=identifiers.museum.get_value() if identifiers.museum else None,
            p_number=identifiers.p_number.get_value() if identifiers.p_number else None,
            uploader_id=uploader_id,
            uploader=Uploader.ADMIN,
            metadata=metadata,
            use_start_time=self._get_time_in_numbers()
        )
        self.insert_text(text=new_text)

        return new_text.text_id

    def _create_new_transliteration(self, text_id: int, dto: TransliterationSubmitDto, uploader_id: str) -> int:
        transliteration_id = randint(100000000, 9999999999)
        transliteration_submission = TransliterationSubmission(
            transliteration_id=transliteration_id,
            source=dto.source,
            image_name=dto.image_name,
            edit_history=[],
            url=dto.url,
            uploader_id=uploader_id
        )
        self._add_transliteration_submission(text_id=text_id,
                                             transliteration_submission=transliteration_submission)
        return transliteration_id

    def _add_transliteration_submission(self, text_id: int,
                                        transliteration_submission: TransliterationSubmission):
        print(transliteration_submission.dict(by_alias=True))
        self._collection.update_one(
            {"text_id": text_id},
            {"$push": {'transliterations': transliteration_submission.dict(by_alias=True)}}
        )

    def process_text_result(self, submit_dto: SubmitDto, user_id: str):
        self._save_progress(submit_dto=submit_dto, user_id=user_id)

    def _save_progress(self, submit_dto: SubmitDto, user_id: str):
        text_progress = TextProgress(items=submit_dto.items,
                                     submit_time=datetime.datetime.now().isoformat(),
                                     user_email=user_id)

        self._collection.update(
            {"text_id": submit_dto.text_id},
            {"$push": {'edit_history': text_progress.dict()}}
        )

    def _add_text_submit_history(self, text_id):
        pass

    def get_text(self, text_id) -> NewText:
        result = self._collection.find_one(filter={"text_id": int(text_id)})
        if result:
            text: NewText = NewText.parse_obj(result)
            return text
        return None

    def delete_transliteration(self, text_id: int, transliteration_id: int) -> int:
        """Delete a transliteration and its image. Returns remaining transliteration count."""
        text = self.get_by_text_id(text_id=text_id)
        if not text:
            return -1

        # Find the transliteration to get its image_name before deleting
        trans = next((t for t in text.transliterations if t.transliteration_id == transliteration_id), None)
        if trans and trans.image_name:
            # Delete image file and preview
            image_path = StorageUtils.build_cured_train_image_path(image_name=trans.image_name)
            preview_path = StorageUtils.build_preview_image_path(image_name=trans.image_name)
            for path in [image_path, preview_path]:
                if os.path.isfile(path):
                    os.remove(path)
                    logging.info(f"Deleted file: {path}")

        # Remove the transliteration from the array
        self._collection.update_one(
            {"text_id": text_id},
            {"$pull": {"transliterations": {"transliteration_id": transliteration_id}}}
        )

        # Return remaining transliteration count
        updated_text = self.get_by_text_id(text_id=text_id)
        return len(updated_text.transliterations) if updated_text else 0

    def delete_text(self, text_id: int):
        """Delete an entire text document."""
        self._collection.delete_one({"text_id": int(text_id)})
        logging.info(f"Deleted text {text_id}")

    def update_label(self, text_id: int, label: str):
        """Update the label of a text entry."""
        self._collection.update_one(
            {"text_id": int(text_id)},
            {"$set": {"label": label}}
        )
        logging.info(f"Updated label for text {text_id} to '{label}'")

    def update_part(self, text_id: int, part: str):
        """Update the part identifier of a text entry."""
        self._collection.update_one(
            {"text_id": int(text_id)},
            {"$set": {"part": part}}
        )
        logging.info(f"Updated part for text {text_id} to '{part}'")

    def get_all_labels(self) -> list:
        """Return all distinct non-empty labels."""
        labels = self._collection.distinct("label", {"label": {"$ne": "", "$exists": True}})
        return sorted(labels)

    def get_amendment_stats(self) -> AmendmentStats:
        completed_text_amount = self._collection.count_documents({"is_fixed": True})
        path = StorageUtils.get_confirmed_signs_path()

        signs_amount = -1
        if platform.system() == 'Linux':
            signs_amount_raw = os.popen(f"find {path} -type f | wc -l").read()
            print(signs_amount_raw)
            signs_amount = int(signs_amount_raw.replace("\n", ""))

        return AmendmentStats(completed_texts=completed_text_amount,
                              saved_signs=signs_amount)

    def get_curated_training_stats(self) -> dict:
        """Get statistics about curated texts for training the Kraken OCR model."""
        # Simpler approach: count texts with is_fixed=True at the document level
        # and also count texts that have CuReD transliterations with is_fixed edits

        curated_texts = 0
        total_lines = 0

        # Find all texts with CuReD transliterations
        cursor = self._collection.find({
            "transliterations": {
                "$elemMatch": {
                    "source": TransliterationSource.CURED.value
                }
            }
        })

        for doc in cursor:
            for trans in doc.get("transliterations", []):
                if trans.get("source") != TransliterationSource.CURED.value:
                    continue

                edit_history = trans.get("edit_history", [])
                if not edit_history:
                    continue

                # Check the latest edit for is_fixed status
                latest_edit = edit_history[-1] if edit_history else None
                if latest_edit and latest_edit.get("is_fixed", False):
                    curated_texts += 1
                    lines = latest_edit.get("lines", [])
                    total_lines += len(lines)

        logging.info(f"Curated training stats: {curated_texts} texts, {total_lines} lines")

        return {"curated_texts": curated_texts, "total_lines": total_lines}

    def get_curated_training_data(self) -> list:
        """
        Get all curated training data for Kraken OCR training.
        Returns a list of dicts with image_path, lines, and boxes.
        """
        from utils.storage_utils import StorageUtils

        training_data = []

        # Find all texts with CuReD transliterations
        cursor = self._collection.find({
            "transliterations": {
                "$elemMatch": {
                    "source": TransliterationSource.CURED.value
                }
            }
        })

        for doc in cursor:
            text_id = doc.get("text_id")

            for trans in doc.get("transliterations", []):
                if trans.get("source") != TransliterationSource.CURED.value:
                    continue

                edit_history = trans.get("edit_history", [])
                if not edit_history:
                    continue

                # Check the latest edit for is_fixed status
                latest_edit = edit_history[-1] if edit_history else None
                if latest_edit and latest_edit.get("is_fixed", False):
                    # Get the image path
                    image_name = trans.get("image_name", "")
                    if image_name:
                        image_path = StorageUtils.build_preview_image_path(image_name)
                    else:
                        image_path = ""

                    lines = latest_edit.get("lines", [])
                    boxes = latest_edit.get("boxes", [])

                    # Convert boxes to dict format if they aren't already
                    box_dicts = []
                    for box in boxes:
                        if isinstance(box, dict):
                            box_dicts.append(box)
                        else:
                            # Assume it's an object with x, y, width, height attributes
                            box_dicts.append({
                                "x": getattr(box, "x", 0),
                                "y": getattr(box, "y", 0),
                                "width": getattr(box, "width", 0),
                                "height": getattr(box, "height", 0)
                            })

                    training_data.append({
                        "text_id": text_id,
                        "image_path": image_path,
                        "lines": lines,
                        "boxes": box_dicts
                    })

        logging.info(f"Found {len(training_data)} curated texts for training")
        return training_data
