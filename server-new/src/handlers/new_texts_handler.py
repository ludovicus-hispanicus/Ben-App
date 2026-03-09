import datetime
import glob as glob_module
from random import randint
from typing import List, Dict

import math
import time
import os
import platform

import pymongo
from PIL import Image

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
        storage_path = os.environ.get("STORAGE_PATH", "data")
        self.KRAKEN_TRAINING_DIR = os.path.join(storage_path, "kraken-training")
        os.makedirs(self.KRAKEN_TRAINING_DIR, exist_ok=True)
        self._load_museums()
        self._migrate_clean_data()

    # ─── Persistent Training Data ─────────────────────────────────────

    def persist_kraken_training_data(self, text_id: int, image_path: str, lines: List[str], boxes: List[dict], project_id: int = None):
        """Crop individual lines from image and save as PNG + .gt.txt in kraken-training/.
        When project_id is set, saves to kraken-training/{project_id}/ subdirectory.
        Re-curation: deletes existing crops for this text first."""
        if len(boxes) != len(lines):
            logging.warning(f"persist_kraken: text {text_id} has {len(boxes)} boxes != {len(lines)} lines, skipping")
            return 0

        # Clean up previous crops for this text
        self._cleanup_kraken_training(text_id, project_id)

        if not os.path.exists(image_path):
            logging.warning(f"persist_kraken: image not found: {image_path}")
            return 0

        try:
            full_image = Image.open(image_path)
        except Exception as e:
            logging.error(f"persist_kraken: cannot open image {image_path}: {e}")
            return 0

        # Determine output directory
        if project_id is not None:
            output_dir = os.path.join(self.KRAKEN_TRAINING_DIR, str(project_id))
        else:
            output_dir = self.KRAKEN_TRAINING_DIR
        os.makedirs(output_dir, exist_ok=True)

        exported = 0
        for i, (line_text, box) in enumerate(zip(lines, boxes)):
            if not line_text.strip():
                continue

            x = box.get("x", 0)
            y = box.get("y", 0)
            width = box.get("width", 0)
            height = box.get("height", 0)
            if width <= 0 or height <= 0:
                continue

            line_image = full_image.crop((x, y, x + width, y + height))
            if line_image.mode != 'L':
                line_image = line_image.convert('L')

            line_filename = f"text{text_id}_line{i:03d}.png"
            gt_filename = f"text{text_id}_line{i:03d}.gt.txt"
            line_image.save(os.path.join(output_dir, line_filename), "PNG")
            with open(os.path.join(output_dir, gt_filename), "w", encoding="utf-8") as f:
                f.write(line_text.strip())
            exported += 1

        logging.info(f"persist_kraken: text {text_id} (project={project_id}) → {exported} line crops saved")
        return exported

    def cleanup_training_data(self, text_id: int, project_id: int = None):
        """Remove all persisted training data for a given text."""
        self._cleanup_kraken_training(text_id, project_id)

    def _cleanup_kraken_training(self, text_id: int, project_id: int = None):
        if project_id is not None:
            base_dir = os.path.join(self.KRAKEN_TRAINING_DIR, str(project_id))
        else:
            base_dir = self.KRAKEN_TRAINING_DIR
        pattern = os.path.join(base_dir, f"text{text_id}_*")
        for f in glob_module.glob(pattern):
            os.remove(f)

    def _find_best_kraken_edit(self, edit_history: list) -> dict:
        """Scan edit_history backward to find the best edit for Kraken training.
        Needs is_curated_kraken=True AND len(boxes)==len(lines).
        Returns the edit dict or None."""
        for edit in reversed(edit_history):
            if not self._is_curated_for(edit, "kraken"):
                continue
            lines = edit.get("lines", [])
            boxes = edit.get("boxes", [])
            if len(boxes) == len(lines) and len(lines) > 0:
                return edit
        return None

    def regenerate_all_training_data(self) -> dict:
        """One-time migration: scan all curated texts, find best Kraken edits, persist line crops."""
        kraken_texts = 0
        kraken_lines = 0

        for doc in self._collection.find({}):
            for trans in doc.get("transliterations", []):
                if trans.get("source") != TransliterationSource.CURED.value:
                    continue
                edit_history = trans.get("edit_history", [])
                if not edit_history:
                    continue

                text_id = doc.get("text_id")
                image_name = trans.get("image_name", "")
                if not image_name:
                    continue
                image_path = StorageUtils.build_cured_train_image_path(image_name)
                if not os.path.exists(image_path):
                    image_path = StorageUtils.build_preview_image_path(image_name)

                best_kraken = self._find_best_kraken_edit(edit_history)
                if best_kraken:
                    proj_id = doc.get("project_id")
                    n = self.persist_kraken_training_data(
                        text_id, image_path,
                        best_kraken.get("lines", []),
                        best_kraken.get("boxes", []),
                        project_id=proj_id
                    )
                    if n > 0:
                        kraken_texts += 1
                        kraken_lines += n

        logging.info(f"regenerate_all: Kraken={kraken_texts} texts ({kraken_lines} lines)")
        return {
            "kraken_texts": kraken_texts,
            "kraken_lines": kraken_lines,
        }

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

    def list_texts(self, limit: int = 1000) -> List[NewTextPreviewDto]:
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)
        result = collection.find_many(find_filter={}, limit=limit, sort=[("use_start_time", pymongo.DESCENDING)])
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

    def _extract_text_content(self, t: 'NewText') -> dict:
        """Extract exportable content from a NewText object."""
        content = ""
        if t.transliterations:
            latest = t.transliterations[-1]
            if latest.edit_history:
                content = "\n".join(latest.edit_history[-1].lines)
        label = t.labels[0] if t.labels else t.label or ""
        return {
            "text_id": t.text_id,
            "label": label,
            "labels": t.labels,
            "part": t.part,
            "content": content,
            "identifier": f"{t.publication_id or ''} {t.museum_id or ''}".strip() or str(t.text_id),
        }

    def export_project_texts(self, project_id: int) -> List[dict]:
        """Export all texts in a project with full content."""
        collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=NewText)
        texts = collection.find_many(
            find_filter={"project_id": int(project_id)},
            limit=10000,
            sort=[("use_start_time", pymongo.DESCENDING)]
        )
        return [self._extract_text_content(t) for t in texts]

    def export_single_text(self, text_id: int) -> dict:
        """Export a single text with full content."""
        t = self.get_text(text_id)
        if not t:
            return None
        return self._extract_text_content(t)

    # ─── CuReD Dataset Export / Import ───────────────────────────────

    def build_cured_export_zip(self, texts: List[NewText], project_id: int = None, project_name: str = None) -> str:
        """Build a self-contained zip with manifest.json + images/.
        Returns path to a temp file (caller must delete)."""
        import tempfile
        import zipfile
        import json

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix="cured_export_")
        tmp.close()

        entries = []
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            for text in texts:
                entry = self._build_export_entry(text, zf)
                entries.append(entry)

            manifest = {
                "version": "1",
                "exported_at": datetime.datetime.utcnow().isoformat(),
                "source_project_id": project_id,
                "source_project_name": project_name,
                "texts": entries,
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        logging.info(f"build_cured_export_zip: {len(entries)} texts, zip={tmp.name}")
        return tmp.name

    def _build_export_entry(self, text: NewText, zf) -> dict:
        """Build one manifest entry and add the image to the zip."""
        # Pick the last CURED transliteration with a non-empty edit_history
        cured_trans = [t for t in text.transliterations
                       if t.source == TransliterationSource.CURED.value
                       and t.edit_history]

        trans_data = None
        image_filename = None

        if cured_trans:
            trans = cured_trans[-1]
            latest_edit = trans.edit_history[-1]

            boxes_raw = latest_edit.boxes or []
            box_dicts = []
            for box in boxes_raw:
                if isinstance(box, dict):
                    box_dicts.append(box)
                else:
                    box_dicts.append({
                        "x": getattr(box, "x", 0),
                        "y": getattr(box, "y", 0),
                        "width": getattr(box, "width", 0),
                        "height": getattr(box, "height", 0),
                    })

            trans_data = {
                "lines": latest_edit.lines,
                "boxes": box_dicts,
                "is_curated_kraken": bool(getattr(latest_edit, "is_curated_kraken", False)),
                "is_curated_vlm": bool(getattr(latest_edit, "is_curated_vlm", False)),
            }

            # Add image to zip if it exists on disk
            if trans.image_name:
                image_path = StorageUtils.build_cured_train_image_path(trans.image_name)
                if not os.path.exists(image_path):
                    image_path = StorageUtils.build_preview_image_path(trans.image_name)
                if os.path.exists(image_path):
                    zip_image_name = f"images/{text.text_id}_{trans.image_name}"
                    zf.write(image_path, zip_image_name)
                    image_filename = zip_image_name

        labels = text.labels if text.labels else ([text.label] if text.label else [])
        return {
            "text_id": text.text_id,
            "museum_id": text.museum_id,
            "p_number": text.p_number,
            "publication_id": text.publication_id,
            "labels": labels,
            "part": text.part or "",
            "image_filename": image_filename,
            "transliteration": trans_data,
        }

    def import_cured_zip(self, zip_path: str, target_project_id: int = None, uploader_id: str = "admin") -> dict:
        """Parse a CuReD export zip and recreate texts.
        Returns {imported, skipped, errors[]}."""
        import zipfile
        import json

        imported = 0
        skipped = 0
        errors = []

        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest_raw = zf.read("manifest.json").decode("utf-8")
            manifest = json.loads(manifest_raw)

            for entry in manifest.get("texts", []):
                try:
                    # 1. Create NewText record (always gets a new text_id)
                    identifiers = TextIdentifiersDto.from_values(
                        museum=entry.get("museum_id"),
                        p_number=entry.get("p_number"),
                        publication=entry.get("publication_id"),
                    )
                    new_text_id = self.create_new_text(
                        identifiers=identifiers,
                        metadata=[],
                        uploader_id=uploader_id,
                        project_id=target_project_id,
                    )

                    # Update labels and part
                    if entry.get("labels"):
                        self.update_labels(new_text_id, entry["labels"])
                    if entry.get("part"):
                        self.update_part(new_text_id, entry["part"])

                    # 2. Save image to disk
                    image_name = None
                    if entry.get("image_filename"):
                        try:
                            img_bytes = zf.read(entry["image_filename"])
                            original_basename = os.path.basename(entry["image_filename"])
                            # Strip the text_id prefix we added during export
                            parts = original_basename.split("_", 1)
                            orig_name = parts[1] if len(parts) > 1 else original_basename
                            image_name = StorageUtils.generate_cured_train_image_name(orig_name, new_text_id)
                            dest_path = StorageUtils.build_cured_train_image_path(image_name)
                            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                            with open(dest_path, "wb") as f:
                                f.write(img_bytes)
                            # Generate preview thumbnail
                            preview_path = StorageUtils.build_preview_image_path(image_name)
                            os.makedirs(os.path.dirname(preview_path), exist_ok=True)
                            StorageUtils.make_a_preview(dest_path, preview_path)
                        except Exception as img_err:
                            logging.warning(f"import: image error for text {entry.get('text_id')}: {img_err}")
                            image_name = None

                    # 3. Create transliteration + edit
                    if entry.get("transliteration"):
                        trans = entry["transliteration"]
                        from entities.dimensions import Dimensions
                        boxes = [Dimensions(**b) for b in trans.get("boxes", [])]
                        dto = TransliterationSubmitDto(
                            text_id=new_text_id,
                            transliteration_id=None,
                            source=TransliterationSource.CURED,
                            lines=trans["lines"],
                            boxes=boxes,
                            image_name=image_name or "",
                            is_curated_kraken=trans.get("is_curated_kraken", False),
                            is_curated_vlm=trans.get("is_curated_vlm", False),
                        )
                        self.save_new_transliteration(dto=dto, uploader_id=uploader_id)

                    imported += 1

                except Exception as e:
                    logging.error(f"import error for entry {entry.get('text_id')}: {e}")
                    errors.append({"original_text_id": entry.get("text_id"), "error": str(e)})

        logging.info(f"import_cured_zip: imported={imported}, skipped={skipped}, errors={len(errors)}")
        return {"imported": imported, "skipped": skipped, "errors": errors}

    def import_cured_folder(self, folder_path: str, target_project_id: int = None, uploader_id: str = "admin") -> dict:
        """Import CuReD data from an unzipped folder containing manifest.json + images/.
        Returns {imported, skipped, errors[]}."""
        import json

        manifest_path = os.path.join(folder_path, "manifest.json")
        if not os.path.exists(manifest_path):
            return {"imported": 0, "skipped": 0, "errors": [{"error": "manifest.json not found in folder"}]}

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        imported = 0
        skipped = 0
        errors = []

        for entry in manifest.get("texts", []):
            try:
                identifiers = TextIdentifiersDto.from_values(
                    museum=entry.get("museum_id"),
                    p_number=entry.get("p_number"),
                    publication=entry.get("publication_id"),
                )
                new_text_id = self.create_new_text(
                    identifiers=identifiers,
                    metadata=[],
                    uploader_id=uploader_id,
                    project_id=target_project_id,
                )

                if entry.get("labels"):
                    self.update_labels(new_text_id, entry["labels"])
                if entry.get("part"):
                    self.update_part(new_text_id, entry["part"])

                # Save image to disk
                image_name = None
                if entry.get("image_filename"):
                    src_image = os.path.join(folder_path, entry["image_filename"])
                    if os.path.exists(src_image):
                        try:
                            original_basename = os.path.basename(entry["image_filename"])
                            parts = original_basename.split("_", 1)
                            orig_name = parts[1] if len(parts) > 1 else original_basename
                            image_name = StorageUtils.generate_cured_train_image_name(orig_name, new_text_id)
                            dest_path = StorageUtils.build_cured_train_image_path(image_name)
                            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                            import shutil
                            shutil.copy2(src_image, dest_path)
                            preview_path = StorageUtils.build_preview_image_path(image_name)
                            os.makedirs(os.path.dirname(preview_path), exist_ok=True)
                            StorageUtils.make_a_preview(dest_path, preview_path)
                        except Exception as img_err:
                            logging.warning(f"import folder: image error for text {entry.get('text_id')}: {img_err}")
                            image_name = None

                if entry.get("transliteration"):
                    trans = entry["transliteration"]
                    from entities.dimensions import Dimensions
                    boxes = [Dimensions(**b) for b in trans.get("boxes", [])]
                    dto = TransliterationSubmitDto(
                        text_id=new_text_id,
                        transliteration_id=None,
                        source=TransliterationSource.CURED,
                        lines=trans["lines"],
                        boxes=boxes,
                        image_name=image_name or "",
                        is_curated_kraken=trans.get("is_curated_kraken", False),
                        is_curated_vlm=trans.get("is_curated_vlm", False),
                    )
                    self.save_new_transliteration(dto=dto, uploader_id=uploader_id)

                imported += 1

            except Exception as e:
                logging.error(f"import folder error for entry {entry.get('text_id')}: {e}")
                errors.append({"original_text_id": entry.get("text_id"), "error": str(e)})

        logging.info(f"import_cured_folder: imported={imported}, skipped={skipped}, errors={len(errors)}")
        return {"imported": imported, "skipped": skipped, "errors": errors}

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
        # Update image_name on existing transliteration when a new image was uploaded
        if dto.transliteration_id and dto.image_name:
            self.update_transliteration_image(dto.text_id, transliteration_id, dto.image_name)
        logging.info(f"Done saving new transliteration for transliteration id {transliteration_id}")

        # Persist Kraken training data (line crops) immediately on curation
        if dto.is_curated_kraken:
            image_path = self._resolve_image_path(dto.text_id, dto.image_name, transliteration_id)
            if image_path:
                boxes = [b.dict() if hasattr(b, 'dict') else b for b in (dto.boxes or [])]
                lines = dto.lines or []
                if len(boxes) == len(lines):
                    # Look up project_id for per-project storage
                    text_doc = self._collection.find_one({"text_id": dto.text_id})
                    proj_id = text_doc.get("project_id") if text_doc else None
                    self.persist_kraken_training_data(dto.text_id, image_path, lines, boxes, project_id=proj_id)

        return transliteration_id

    def _resolve_image_path(self, text_id: int, image_name: str, transliteration_id: int = None) -> str:
        """Resolve image path from image_name, falling back to DB lookup."""
        if image_name:
            path = StorageUtils.build_cured_train_image_path(image_name)
            if os.path.exists(path):
                return path
            path = StorageUtils.build_preview_image_path(image_name)
            if os.path.exists(path):
                return path

        # Fallback: look up image_name from the transliteration record
        if transliteration_id:
            text = self.get_by_text_id(text_id)
            if text:
                trans = next((t for t in text.transliterations if t.transliteration_id == transliteration_id), None)
                if trans and trans.image_name:
                    path = StorageUtils.build_cured_train_image_path(trans.image_name)
                    if os.path.exists(path):
                        return path
        return None

    def save_transliteration_edit(self, text_id: int, transliteration_id: int,
                                  transliteration_edit: TransliterationEdit):
        a = self._collection.update_one(
            {"text_id": text_id, "transliterations.transliteration_id": transliteration_id},  # is it tho?
            {"$push": {'transliterations.$.edit_history': transliteration_edit.dict()}}
        )
        self._update_text_use_time(text_id=text_id)

    def batch_curate(self, text_ids: List[int], curate: bool, target: str = "both", user_id: str = "admin") -> dict:
        """Set or unset curation flags on the latest edit of each text's latest CURED transliteration.

        Optimised: single DB read, mutate all matching texts in memory, single DB write.
        """
        updated = 0
        skipped = 0
        errors = []
        kraken_jobs = []  # collect kraken training data jobs to run after write

        id_set = set(int(tid) for tid in text_ids)
        now_iso = datetime.datetime.now().isoformat()
        use_time = math.floor(time.time())

        # Single read of the full collection
        with self._collection._lock:
            data = self._collection._read_unsafe()

            for item in data:
                tid = item.get("text_id")
                if tid not in id_set:
                    continue
                id_set.discard(tid)

                try:
                    transliterations = item.get("transliterations", [])
                    cured_trans = [t for t in transliterations
                                   if t.get("source") in (TransliterationSource.CURED.value, "cured")]
                    if not cured_trans:
                        skipped += 1
                        continue

                    trans = cured_trans[-1]
                    edit_history = trans.get("edit_history", [])
                    if not edit_history:
                        skipped += 1
                        continue

                    latest_edit = edit_history[-1]

                    is_kraken = curate if target in ("both", "kraken") else latest_edit.get("is_curated_kraken", False)
                    is_vlm = curate if target in ("both", "vlm") else latest_edit.get("is_curated_vlm", False)

                    new_edit = {
                        "lines": latest_edit.get("lines", []),
                        "boxes": latest_edit.get("boxes", []),
                        "user_id": user_id,
                        "time": now_iso,
                        "is_fixed": curate,
                        "is_curated_kraken": is_kraken,
                        "is_curated_vlm": is_vlm,
                    }
                    edit_history.append(new_edit)
                    item["use_start_time"] = use_time

                    # Collect kraken training info (will persist after write)
                    if is_kraken and curate:
                        boxes_raw = latest_edit.get("boxes", [])
                        lines_raw = latest_edit.get("lines", [])
                        if boxes_raw and len(boxes_raw) == len(lines_raw):
                            kraken_jobs.append({
                                "text_id": tid,
                                "image_name": trans.get("image_name"),
                                "transliteration_id": trans.get("transliteration_id"),
                                "lines": lines_raw,
                                "boxes": boxes_raw,
                                "project_id": item.get("project_id"),
                            })

                    updated += 1
                except Exception as e:
                    logging.error(f"batch_curate error for text_id={tid}: {e}")
                    errors.append({"text_id": tid, "error": str(e)})

            skipped += len(id_set)  # remaining ids not found

            # Single write
            if updated > 0:
                self._collection._write_unsafe(data)

        # Persist kraken training data outside the lock (filesystem I/O)
        for job in kraken_jobs:
            try:
                image_path = self._resolve_image_path(job["text_id"], job["image_name"], job["transliteration_id"])
                if image_path:
                    self.persist_kraken_training_data(
                        job["text_id"], image_path, job["lines"], job["boxes"],
                        project_id=job["project_id"],
                    )
            except Exception as e:
                logging.error(f"batch_curate kraken persist error for text_id={job['text_id']}: {e}")

        logging.info(f"batch_curate: updated={updated}, skipped={skipped}, errors={len(errors)}")
        return {"updated": updated, "skipped": skipped, "errors": errors}

    def update_transliteration_image(self, text_id: int, transliteration_id: int, image_name: str):
        """Update the image_name on an existing transliteration record."""
        self._collection.update_one(
            {"text_id": text_id, "transliterations.transliteration_id": transliteration_id},
            {"$set": {"transliterations.$.image_name": image_name}}
        )

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

        # Clean up persisted training data
        self.cleanup_training_data(text_id)

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
        self.cleanup_training_data(text_id)
        self._collection.delete_one({"text_id": int(text_id)})
        logging.info(f"Deleted text {text_id}")

    def delete_texts_batch(self, text_ids: List[int]) -> dict:
        """Delete multiple texts in a single read/write cycle for performance."""
        if not text_ids:
            return {"deleted": 0, "errors": []}

        id_set = set(int(tid) for tid in text_ids)

        # Clean up training data for each text
        for tid in id_set:
            try:
                self.cleanup_training_data(tid)
            except Exception as e:
                logging.warning(f"cleanup_training_data failed for {tid}: {e}")

        # Also clean up image files — need to read texts first
        with self._collection._lock:
            data = self._collection._read_unsafe()

            # Find and remove images for texts being deleted
            for doc in data:
                if doc.get("text_id") not in id_set:
                    continue
                for trans in doc.get("transliterations", []):
                    img = trans.get("image_name", "")
                    if img:
                        for path in [
                            StorageUtils.build_cured_train_image_path(img),
                            StorageUtils.build_preview_image_path(img),
                        ]:
                            if os.path.isfile(path):
                                try:
                                    os.remove(path)
                                except Exception:
                                    pass

            # Filter out deleted texts in one pass
            original_count = len(data)
            data = [doc for doc in data if doc.get("text_id") not in id_set]
            deleted_count = original_count - len(data)

            # Single write
            self._collection._write_unsafe(data)

        logging.info(f"Batch deleted {deleted_count} texts (requested {len(id_set)})")
        return {"deleted": deleted_count, "errors": []}

    def remove_tile_markers(self, project_id: int = None, text_ids: List[int] = None) -> dict:
        """Remove ************************ tile merge marker lines from texts.
        If project_id is given, processes all texts in that project.
        If text_ids is given, processes only those texts.
        Returns {cleaned: int, total_markers_removed: int}.
        """
        from handlers.batch_recognition_handler import TILE_MERGE_MARKER

        with self._collection._lock:
            data = self._collection._read_unsafe()

            cleaned = 0
            total_removed = 0

            for doc in data:
                if project_id and doc.get("project_id") != project_id:
                    continue
                if text_ids and doc.get("text_id") not in text_ids:
                    continue

                changed = False
                for trans in doc.get("transliterations", []):
                    for edit in trans.get("edit_history", []):
                        lines = edit.get("lines", [])
                        original_len = len(lines)
                        filtered = [l for l in lines if l.strip() != TILE_MERGE_MARKER]
                        removed = original_len - len(filtered)
                        if removed > 0:
                            edit["lines"] = filtered
                            total_removed += removed
                            changed = True
                            # Also update boxes if present (remove corresponding box entries)
                            boxes = edit.get("boxes", [])
                            if boxes and len(boxes) == original_len:
                                new_boxes = [b for l, b in zip(lines, boxes) if l.strip() != TILE_MERGE_MARKER]
                                edit["boxes"] = new_boxes

                if changed:
                    cleaned += 1

            if total_removed > 0:
                self._collection._write_unsafe(data)

        logging.info(f"Tile marker cleanup: cleaned {cleaned} texts, removed {total_removed} marker lines")
        return {"cleaned": cleaned, "total_markers_removed": total_removed}

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

    def get_curated_training_stats(self, target: str = None, project_id: int = None, project_ids: list = None) -> dict:
        """Get statistics about curated texts for training.
        If target is specified ("vlm" or "kraken"), only count texts with that target.
        If project_ids is specified, only count texts in those projects.
        If project_id is specified (legacy), only count texts in that project.
        For "kraken", also validates that boxes match lines (line-level annotation)."""

        curated_texts = 0
        total_lines = 0
        skipped_wrong_boxes = 0

        query = {
            "transliterations": {
                "$elemMatch": {
                    "source": TransliterationSource.CURED.value
                }
            }
        }
        if project_ids:
            query["project_id"] = {"$in": [int(pid) for pid in project_ids]}
        elif project_id is not None:
            query["project_id"] = int(project_id)

        cursor = self._collection.find(query)

        for doc in cursor:
            for trans in doc.get("transliterations", []):
                if trans.get("source") != TransliterationSource.CURED.value:
                    continue

                edit_history = trans.get("edit_history", [])
                if not edit_history:
                    continue

                latest_edit = edit_history[-1]
                if self._is_curated_for(latest_edit, target):
                    lines = latest_edit.get("lines", [])
                    boxes = latest_edit.get("boxes", [])

                    # For Kraken, only count texts with line-level boxes
                    if target == "kraken" and len(boxes) != len(lines):
                        skipped_wrong_boxes += 1
                        continue

                    curated_texts += 1
                    total_lines += len(lines)

        logging.info(f"Curated training stats (target={target}): {curated_texts} texts, {total_lines} lines"
                     + (f", skipped {skipped_wrong_boxes} with mismatched boxes" if skipped_wrong_boxes else ""))
        return {
            "curated_texts": curated_texts,
            "total_lines": total_lines,
            "skipped_wrong_boxes": skipped_wrong_boxes
        }

    def get_curated_training_data(self, target: str = None, project_id: int = None, project_ids: list = None) -> list:
        """
        Get curated training data, optionally filtered by target ("vlm" or "kraken")
        and/or project_id(s). Returns a list of dicts with image_path, lines, and boxes.
        """
        from utils.storage_utils import StorageUtils

        training_data = []

        query = {
            "transliterations": {
                "$elemMatch": {
                    "source": TransliterationSource.CURED.value
                }
            }
        }
        if project_ids:
            query["project_id"] = {"$in": [int(pid) for pid in project_ids]}
        elif project_id is not None:
            query["project_id"] = int(project_id)

        cursor = self._collection.find(query)

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
                    if not os.path.exists(image_path):
                        # image_name may be stale — try matching by text_id prefix
                        text_id_prefix = str(text_id) + "_"
                        for search_dir in [
                            os.path.join(StorageUtils.BASE_PATH, StorageUtils.CURED_TRAINING_DATA_DIR_NAME),
                            os.path.join(StorageUtils.BASE_PATH, StorageUtils.PREVIEW_DIR_NAME),
                        ]:
                            if os.path.isdir(search_dir):
                                matches = [f for f in os.listdir(search_dir) if f.startswith(text_id_prefix)]
                                if matches:
                                    image_path = os.path.join(search_dir, matches[0])
                                    logging.info(f"Resolved stale image_name {image_name} -> {matches[0]}")
                                    break
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

        logging.info(f"Found {len(training_data)} curated texts for training (target={target}, project_ids={project_ids or project_id})")
        return training_data

    def get_curated_training_data_for(self, target: str, project_id: int = None, project_ids: list = None) -> list:
        """
        Get curated training data filtered by training target and optionally project(s).
        target: "vlm" or "kraken"
        """
        return self.get_curated_training_data(target=target, project_id=project_id, project_ids=project_ids)
