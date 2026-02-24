import datetime
import logging
import os
from random import randint
from typing import List, Dict, Optional
from uuid import uuid4

from entities.production_text import ProductionText, ProductionEdit, SourceTextReference, IdentifierType, UploadedImage
from mongo.local_db_client import LocalDBClient as MongoClient
from utils.storage_utils import StorageUtils


class ProductionTextsHandler:
    COLLECTION_NAME = "production_texts"

    def __init__(self):
        self._collection = MongoClient.get_db().production_texts

    def get_all(self) -> List[ProductionText]:
        """Get all production texts."""
        data = self._collection.find_many({})
        return [ProductionText.parse_obj(d) for d in data]

    def get_by_id(self, production_id: int) -> Optional[ProductionText]:
        """Get a production text by its ID."""
        data = self._collection.find_one({"production_id": int(production_id)})
        if data:
            return ProductionText.parse_obj(data)
        return None

    def get_by_identifier(self, identifier: str, identifier_type: IdentifierType) -> Optional[ProductionText]:
        """Get a production text by its identifier."""
        data = self._collection.find_one({
            "identifier": identifier,
            "identifier_type": identifier_type.value
        })
        if data:
            return ProductionText.parse_obj(data)
        return None

    def get_grouped_by_identifier(self) -> Dict[str, List[Dict]]:
        """
        Get all production texts grouped by identifier.
        Returns a dict where keys are identifiers and values are lists of production texts.
        """
        all_texts = self.get_all()
        grouped = {}
        for text in all_texts:
            if text.identifier not in grouped:
                grouped[text.identifier] = []
            grouped[text.identifier].append({
                "production_id": text.production_id,
                "identifier": text.identifier,
                "identifier_type": text.identifier_type,
                "source_count": len(text.source_texts),
                "last_modified": text.last_modified,
                "has_content": bool(text.content),
            })
        return grouped

    def create(
        self,
        identifier: str,
        identifier_type: IdentifierType,
        source_texts: List[SourceTextReference],
        uploader_id: str,
        initial_content: str = ""
    ) -> ProductionText:
        """Create a new production text."""
        now = datetime.datetime.now().isoformat()
        production_id = randint(100000000, 9999999999)

        edit_history = []
        if initial_content:
            edit_history.append(ProductionEdit(
                content=initial_content,
                time=now,
                user_id=uploader_id
            ))

        production_text = ProductionText(
            production_id=production_id,
            identifier=identifier,
            identifier_type=identifier_type,
            source_texts=source_texts,
            content=initial_content,
            edit_history=edit_history,
            created_at=now,
            last_modified=now,
            uploader_id=uploader_id
        )

        self._collection.insert_one(production_text.dict())
        logging.info(f"Created production text {production_id} for {identifier}")
        return production_text

    def update_content(
        self,
        production_id: int,
        content: str,
        user_id: str,
        translation_content: Optional[str] = None
    ) -> Optional[ProductionText]:
        """Update the content of a production text."""
        now = datetime.datetime.now().isoformat()

        # Create new edit entry
        edit = ProductionEdit(
            content=content,
            time=now,
            user_id=user_id
        )

        # Build update dict
        update_fields = {"content": content, "last_modified": now}
        if translation_content is not None:
            update_fields["translation_content"] = translation_content

        # Update the document
        self._collection.update_one(
            {"production_id": int(production_id)},
            {"$set": update_fields}
        )

        # Push to edit history
        self._collection.update_one(
            {"production_id": int(production_id)},
            {"$push": {"edit_history": edit.dict()}}
        )

        logging.info(f"Updated production text {production_id}")
        return self.get_by_id(production_id)

    def update_source_texts(
        self,
        production_id: int,
        source_texts: List[SourceTextReference]
    ) -> Optional[ProductionText]:
        """Update the source text references."""
        now = datetime.datetime.now().isoformat()

        self._collection.update_one(
            {"production_id": int(production_id)},
            {"$set": {
                "source_texts": [s.dict() for s in source_texts],
                "last_modified": now
            }}
        )

        logging.info(f"Updated source texts for production text {production_id}")
        return self.get_by_id(production_id)

    def delete(self, production_id: int) -> bool:
        """Delete a production text."""
        result = self._collection.delete_one({"production_id": int(production_id)})
        if result:
            logging.info(f"Deleted production text {production_id}")
        return result

    def mark_exported(self, production_id: int, exported: bool = True) -> bool:
        """Mark a production text as exported (or not)."""
        now = datetime.datetime.now().isoformat()

        self._collection.update_one(
            {"production_id": int(production_id)},
            {"$set": {"is_exported": exported, "last_modified": now}}
        )

        logging.info(f"Marked production text {production_id} as exported={exported}")
        return True

    def generate_merged_content(self, source_texts: List[Dict]) -> str:
        """
        Generate merged content from source texts.
        Each source text dict should have 'part' and 'lines' keys.
        Parts are sorted by part number and concatenated.
        """
        # Sort by part
        sorted_sources = sorted(source_texts, key=lambda x: x.get('part', ''))

        merged_lines = []
        for source in sorted_sources:
            part = source.get('part', '')
            lines = source.get('lines', [])

            if part:
                merged_lines.append(f"# Part {part}")
            merged_lines.extend(lines)
            merged_lines.append("")  # Empty line between parts

        return "\n".join(merged_lines).strip()

    def add_uploaded_image(
        self,
        production_id: int,
        image_data: bytes,
        original_filename: str,
        label: str
    ) -> Optional[UploadedImage]:
        """Add an uploaded image to a production text."""
        prod_text = self.get_by_id(production_id)
        if not prod_text:
            return None

        now = datetime.datetime.now().isoformat()
        image_id = str(uuid4())

        # Save image to disk
        image_path = StorageUtils.build_production_image_path(production_id, image_id)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)

        with open(image_path, 'wb') as f:
            f.write(image_data)

        logging.info(f"Saved production image {image_id} to {image_path}")

        # Create image reference
        uploaded_image = UploadedImage(
            image_id=image_id,
            image_name=original_filename,
            label=label,
            uploaded_at=now
        )

        # Update the document
        self._collection.update_one(
            {"production_id": int(production_id)},
            {
                "$push": {"uploaded_images": uploaded_image.dict()},
                "$set": {"last_modified": now}
            }
        )

        logging.info(f"Added uploaded image {image_id} to production text {production_id}")
        return uploaded_image

    def get_uploaded_image_path(self, production_id: int, image_id: str) -> Optional[str]:
        """Get the file path for an uploaded image."""
        prod_text = self.get_by_id(production_id)
        if not prod_text:
            return None

        # Check that the image exists in the production text
        image_exists = any(img.image_id == image_id for img in prod_text.uploaded_images)
        if not image_exists:
            return None

        image_path = StorageUtils.build_production_image_path(production_id, image_id)
        if os.path.exists(image_path):
            return image_path

        return None

    def delete_uploaded_image(self, production_id: int, image_id: str) -> bool:
        """Delete an uploaded image from a production text."""
        prod_text = self.get_by_id(production_id)
        if not prod_text:
            return False

        # Check that the image exists
        image_exists = any(img.image_id == image_id for img in prod_text.uploaded_images)
        if not image_exists:
            return False

        now = datetime.datetime.now().isoformat()

        # Remove from database
        self._collection.update_one(
            {"production_id": int(production_id)},
            {
                "$pull": {"uploaded_images": {"image_id": image_id}},
                "$set": {"last_modified": now}
            }
        )

        # Delete file from disk
        image_path = StorageUtils.build_production_image_path(production_id, image_id)
        if os.path.exists(image_path):
            os.remove(image_path)
            logging.info(f"Deleted production image file {image_path}")

        logging.info(f"Deleted uploaded image {image_id} from production text {production_id}")
        return True


# Global instance
production_texts_handler = ProductionTextsHandler()
