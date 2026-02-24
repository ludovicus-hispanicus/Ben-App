import datetime
from random import randint
from typing import List, Dict

import math
import time
import os
import platform

import pymongo

from api.dto.submissions import TransliterationSubmissionPreview, TextIdentifiersDto, TransliterationSubmitDto
from api.dto.text import NewTextPreviewDto, GalleryItemDto
from entities.new_text import NewText, TransliterationSubmission, TransliterationEdit, TransliterationSource, Uploader
from mongo.local_db_client import LocalDBClient as MongoClient, MongoCursor

from mongo.mongo_collection import MongoCollection
from utils.storage_utils import StorageUtils
import logging


class NewTextsHandler:
    COLLECTION_NAME = "new_texts"

    def __init__(self):
        print("new text handler called")
        self._collection = MongoClient.get_db().new_texts
        self._load_museums()
        self._migrate_clean_data()

    def _load_museums(self):
        self.museums = []
        try:
            museums_path = StorageUtils.get_museums_file_path()
            if os.path.exists(museums_path):
                with open(museums_path, encoding="utf-8") as new_csv:
                    for line in new_csv.readlines():
                        items = line.split(",", 1)
                        museum_name = items[0]
                        description = items[1].replace("\"", "") if len(items) > 1 else ""
                        museum = f"{museum_name} - {description}"
                        self.museums.append(museum)
        except Exception as e:
            logging.warning(f"Could not load museums.csv: {e}")

    def _migrate_clean_data(self):
        """One-time migration: strip 'Part-' prefix from parts, strip '-0' suffix from identifiers."""
        import re
        count = 0
        for doc in self._collection.find({}):
            updates = {}
            # Strip "Part-" prefix from part values
            part = doc.get("part", "")
            if isinstance(part, str) and part.startswith("Part-"):
                updates["part"] = part[5:]

            # Strip trailing "-0" from identifier fields (artifact of TextIdentifier.get_value())
            for field in ("museum_id", "p_number", "publication_id"):
                val = doc.get(field, "")
                if isinstance(val, str) and val.endswith("-0"):
                    updates[field] = val[:-2]

            if updates:
                self._collection.update_one(
                    {"text_id": doc["text_id"]},
                    {"$set": updates}
                )
                count += 1

        # Also clean production_texts source references
        prod_collection = MongoClient.get_db().production_texts
        for doc in prod_collection.find_many({}):
            sources = doc.get("source_texts", [])
            prod_updates = {}
            updated = False
            for source in sources:
                p = source.get("part", "")
                if isinstance(p, str) and p.startswith("Part-"):
                    source["part"] = p[5:]
                    updated = True
            if updated:
                prod_updates["source_texts"] = sources

            # Strip "-0" from production text identifier
            identifier = doc.get("identifier", "")
            if isinstance(identifier, str) and identifier.endswith("-0"):
                prod_updates["identifier"] = identifier[:-2]

            if prod_updates:
                prod_collection.update_one(
                    {"production_id": doc["production_id"]},
                    {"$set": prod_updates}
                )
                count += 1

        if count > 0:
            logging.info(f"Migration: cleaned {count} records (Part- prefix, -0 suffix)")

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

        # Filter out None values (transliterations with empty edit_history)
        previews = [TransliterationSubmissionPreview.from_transliteration_entity(trans)
                    for trans in cured_transliterations]
        previews = [p for p in previews if p is not None]

        return previews

    def list_texts(self) -> List[NewTextPreviewDto]:
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)
        result = collection.find_many(find_filter={}, limit=1000, sort=[("use_start_time", pymongo.DESCENDING)])
        previews = [NewTextPreviewDto.from_new_text(new_text=new_text) for new_text in result]

        return previews

    def list_texts_by_project(self, project_id: int) -> List[NewTextPreviewDto]:
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)
        result = collection.find_many(
            find_filter={"project_id": int(project_id)},
            limit=1000,
            sort=[("use_start_time", pymongo.DESCENDING)]
        )
        return [NewTextPreviewDto.from_new_text(new_text=t) for t in result]

    def list_unassigned_texts(self) -> List[NewTextPreviewDto]:
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)
        all_texts = collection.find_many(find_filter={}, limit=1000, sort=[("use_start_time", pymongo.DESCENDING)])
        unassigned = [t for t in all_texts if not getattr(t, 'project_id', None)]
        return [NewTextPreviewDto.from_new_text(new_text=t) for t in unassigned]

    def assign_text_to_project(self, text_id: int, project_id: int):
        self._update_text(text_id=text_id, new_values={"project_id": project_id})

    def unassign_texts_from_project(self, project_id: int):
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)
        texts = collection.find_many(find_filter={"project_id": int(project_id)}, limit=10000)
        for text in texts:
            self._update_text(text_id=text.text_id, new_values={"project_id": None})

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

    def search_kwic(self, query: str, limit: int = 200) -> list:
        """Search all transliteration lines for a query string and return KWIC results."""
        import re
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)

        # Load all texts (LocalDBClient doesn't support $regex queries)
        all_texts = collection.find_many(find_filter={}, limit=1000)
        if not all_texts:
            return []

        kwic_results = []
        pattern = re.compile(re.escape(query), re.IGNORECASE)

        for text in all_texts:
            identifier, identifier_type = None, "unknown"
            if text.museum_id:
                identifier, identifier_type = text.museum_id, "museum"
            elif text.p_number:
                identifier, identifier_type = text.p_number, "p_number"
            elif text.publication_id:
                identifier, identifier_type = text.publication_id, "publication"
            else:
                identifier = f"unknown_{text.text_id}"

            if not text.transliterations or not text.transliterations[-1].edit_history:
                continue
            lines = text.transliterations[-1].edit_history[-1].lines

            for i, line in enumerate(lines):
                if pattern.search(line):
                    kwic_results.append({
                        "text_id": text.text_id,
                        "identifier": identifier,
                        "identifier_type": identifier_type,
                        "part": getattr(text, 'part', '') or '',
                        "line_index": i,
                        "line_before": lines[i - 1] if i > 0 else None,
                        "matching_line": line,
                        "line_after": lines[i + 1] if i < len(lines) - 1 else None,
                    })
                    if len(kwic_results) >= limit:
                        return kwic_results

        return kwic_results

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
            is_fixed=dto.is_fixed,
            is_curated_kraken=dto.is_curated_kraken,
            is_curated_vlm=dto.is_curated_vlm,
            training_targets=dto.training_targets
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

    def create_new_text(self, identifiers: TextIdentifiersDto, metadata: List[Dict], uploader_id: str, project_id: int = None) -> int:
        new_text = NewText(
            text_id=randint(1000000, 9999999),
            publication_id=identifiers.publication.get_value() if identifiers.publication else None,
            museum_id=identifiers.museum.get_value() if identifiers.museum else None,
            p_number=identifiers.p_number.get_value() if identifiers.p_number else None,
            uploader_id=uploader_id,
            uploader=Uploader.ADMIN,
            metadata=metadata,
            use_start_time=self._get_time_in_numbers(),
            project_id=project_id
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
        """Update the label of a text entry (legacy single label)."""
        self.update_labels(text_id, [label] if label else [])

    def update_labels(self, text_id: int, labels: list):
        """Update the labels of a text entry."""
        self._collection.update_one(
            {"text_id": int(text_id)},
            {"$set": {"labels": labels, "label": labels[0] if labels else ""}}
        )
        logging.info(f"Updated labels for text {text_id} to {labels}")

    @staticmethod
    def _sanitize_part(part: str) -> str:
        """Strip 'Part-' prefix, keeping only the number."""
        if part and part.startswith("Part-"):
            return part[5:]
        return part

    def update_part(self, text_id: int, part: str):
        """Update the part identifier of a text entry."""
        part = self._sanitize_part(part)
        self._collection.update_one(
            {"text_id": int(text_id)},
            {"$set": {"part": part}}
        )
        logging.info(f"Updated part for text {text_id} to '{part}'")

    def update_identifiers(self, text_id: int, museum_id: str = None, p_number: str = None, publication_id: str = None):
        """Update the identifiers of a text entry."""
        self._collection.update_one(
            {"text_id": int(text_id)},
            {"$set": {"museum_id": museum_id, "p_number": p_number, "publication_id": publication_id}}
        )
        logging.info(f"Updated identifiers for text {text_id}")

    def get_all_labels(self) -> list:
        """Return all distinct non-empty labels from both labels array and legacy label field."""
        label_set = set()
        for doc in self._collection.find({}):
            # New format: labels array
            labels = doc.get("labels", [])
            if isinstance(labels, list):
                for l in labels:
                    if l:
                        label_set.add(l)
            # Legacy format: single label string
            label = doc.get("label", "")
            if label and isinstance(label, str):
                label_set.add(label)
        return sorted(label_set)



    def _is_curated_for(self, latest_edit: dict, target: str = None) -> bool:
        """Check if an edit is curated, optionally for a specific target.
        Handles both new (is_curated_kraken/vlm) and legacy (is_fixed + training_targets) data."""
        is_kraken = latest_edit.get("is_curated_kraken", False)
        is_vlm = latest_edit.get("is_curated_vlm", False)

        # Legacy fallback
        if not is_kraken and not is_vlm and latest_edit.get("is_fixed", False):
            targets = latest_edit.get("training_targets") or []
            is_kraken = "kraken" in targets or not targets
            is_vlm = "vlm" in targets or not targets

        if target == "kraken":
            return is_kraken
        elif target == "vlm":
            return is_vlm
        else:
            return is_kraken or is_vlm

    def get_curated_training_stats(self, target: str = None) -> dict:
        """Get statistics about curated texts for training.
        If target is specified ("vlm" or "kraken"), only count texts with that target."""

        curated_texts = 0
        total_lines = 0

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

                latest_edit = edit_history[-1]
                if self._is_curated_for(latest_edit, target):
                    curated_texts += 1
                    total_lines += len(latest_edit.get("lines", []))

        logging.info(f"Curated training stats (target={target}): {curated_texts} texts, {total_lines} lines")
        return {"curated_texts": curated_texts, "total_lines": total_lines}

    def get_curated_training_data(self, target: str = None) -> list:
        """
        Get curated training data, optionally filtered by target ("vlm" or "kraken").
        Returns a list of dicts with image_path, lines, and boxes.
        """
        from utils.storage_utils import StorageUtils

        training_data = []

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

                latest_edit = edit_history[-1]
                if not self._is_curated_for(latest_edit, target):
                    continue

                image_name = trans.get("image_name", "")
                if image_name:
                    image_path = StorageUtils.build_cured_train_image_path(image_name)
                    if not os.path.exists(image_path):
                        image_path = StorageUtils.build_preview_image_path(image_name)
                else:
                    image_path = ""

                lines = latest_edit.get("lines", [])
                boxes = latest_edit.get("boxes", [])

                box_dicts = []
                for box in boxes:
                    if isinstance(box, dict):
                        box_dicts.append(box)
                    else:
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
                    "boxes": box_dicts,
                    "is_curated_kraken": self._is_curated_for(latest_edit, "kraken"),
                    "is_curated_vlm": self._is_curated_for(latest_edit, "vlm"),
                })

        logging.info(f"Found {len(training_data)} curated texts for training (target={target})")
        return training_data

    def get_curated_training_data_for(self, target: str) -> list:
        """
        Get curated training data filtered by training target.
        target: "vlm" or "kraken"
        """
        return self.get_curated_training_data(target=target)
