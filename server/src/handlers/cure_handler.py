"""
CuRe Handler — Business logic for CuRe training data management.
"""
import base64
import csv
import io
import json
import logging
import os
import shutil
from typing import Dict, Optional

import cv2
import numpy as np
from PIL import Image


def _get_storage_path() -> str:
    return os.environ.get("STORAGE_PATH", "data")


class CuReHandler:
    """Handles CuRe annotation uploads, model imports, and data stats."""

    def __init__(self):
        self.storage_path = _get_storage_path()
        self.training_dir = os.path.join(self.storage_path, "cure-training")
        self.annotations_dir = os.path.join(self.training_dir, "annotations")
        self.crops_dir = os.path.join(self.training_dir, "crops")
        self.models_dir = os.path.join(self.storage_path, "cure_models")

    def _ensure_dirs(self):
        """Create data directories if they don't exist."""
        os.makedirs(self.annotations_dir, exist_ok=True)
        os.makedirs(self.crops_dir, exist_ok=True)
        os.makedirs(self.models_dir, exist_ok=True)

    def upload_annotation(
        self,
        image_base64: str,
        annotations_csv: str,
        image_name: Optional[str] = None,
    ) -> Dict:
        """
        Upload a tablet image with sign-level annotations.

        Args:
            image_base64: Base64 encoded tablet image
            annotations_csv: CSV content with x1,y1,x2,y2,label columns
            image_name: Optional name for the annotation set

        Returns:
            Dict with upload stats.
        """
        self._ensure_dirs()

        # Generate name if not provided
        if not image_name:
            existing = os.listdir(self.annotations_dir)
            image_name = f"tablet_{len(existing) + 1:04d}"

        tablet_dir = os.path.join(self.annotations_dir, image_name)
        os.makedirs(tablet_dir, exist_ok=True)

        # Save image
        if image_base64.startswith("data:"):
            comma_idx = image_base64.find(",")
            if comma_idx != -1:
                image_base64 = image_base64[comma_idx + 1:]

        image_data = base64.b64decode(image_base64)
        image_path = os.path.join(tablet_dir, "image.png")
        with open(image_path, "wb") as f:
            f.write(image_data)

        # Save annotations CSV
        csv_path = os.path.join(tablet_dir, "annotations.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(annotations_csv)

        # Extract and save crops
        pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")
        num_crops = self._extract_crops(pil_image, annotations_csv, image_name)

        # Update manifest
        self._update_manifest()

        logging.info(f"CuRe annotation uploaded: {image_name}, {num_crops} crops extracted")
        return {
            "image_name": image_name,
            "crops_extracted": num_crops,
            "annotations_path": csv_path,
        }

    def _extract_crops(self, pil_image: Image.Image, csv_content: str, source_name: str) -> int:
        """Extract 64x64 sign crops from image using annotation bounding boxes."""
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0

        for row in reader:
            try:
                x1 = int(float(row.get("x1", 0)))
                y1 = int(float(row.get("y1", 0)))
                x2 = int(float(row.get("x2", 0)))
                y2 = int(float(row.get("y2", 0)))
                label = row.get("label", "").strip()

                if not label:
                    continue

                crop = pil_image.crop((x1, y1, x2, y2))
                crop = crop.resize((64, 64))

                # Save to label subdirectory
                label_dir = os.path.join(self.crops_dir, label)
                os.makedirs(label_dir, exist_ok=True)

                crop_name = f"{source_name}_{count:05d}.png"
                crop.save(os.path.join(label_dir, crop_name))
                count += 1
            except (ValueError, KeyError) as e:
                logging.warning(f"Skipping annotation row: {e}")
                continue

        return count

    def _update_manifest(self):
        """Update the training data manifest with current stats."""
        manifest = self.get_annotation_stats()
        manifest_path = os.path.join(self.training_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def get_annotation_stats(self) -> Dict:
        """Get statistics about the current training data."""
        stats = {
            "total_crops": 0,
            "total_labels": 0,
            "total_tablets": 0,
            "label_distribution": {},
        }

        # Count tablets
        if os.path.exists(self.annotations_dir):
            stats["total_tablets"] = len([
                d for d in os.listdir(self.annotations_dir)
                if os.path.isdir(os.path.join(self.annotations_dir, d))
            ])

        # Count crops per label
        if os.path.exists(self.crops_dir):
            for label_name in os.listdir(self.crops_dir):
                label_path = os.path.join(self.crops_dir, label_name)
                if os.path.isdir(label_path):
                    count = len([
                        f for f in os.listdir(label_path)
                        if f.endswith(".png")
                    ])
                    stats["label_distribution"][label_name] = count
                    stats["total_crops"] += count

            stats["total_labels"] = len(stats["label_distribution"])

        return stats

    def import_pretrained(
        self, model_pt_path: str, labels_path: str, model_name: str = "imported"
    ) -> Dict:
        """
        Import a pre-trained CuRe model and its label mapping.

        Args:
            model_pt_path: Path to .pt state_dict file
            labels_path: Path to labels CSV or JSON mapping file
            model_name: Name for the imported model

        Returns:
            Dict with import status.
        """
        self._ensure_dirs()

        # Copy model file
        dest_model = os.path.join(self.models_dir, f"{model_name}.pt")
        shutil.copy2(model_pt_path, dest_model)

        # Import label mapping
        from services.cure_label_service import CuReLabelService
        label_service = CuReLabelService()

        if labels_path.endswith(".json"):
            label_service.load_mapping(labels_path)
        elif labels_path.endswith(".csv"):
            label_service.import_from_csv(labels_path)
        else:
            raise ValueError(f"Unsupported labels file format: {labels_path}")

        # Save mapping in standard format
        mapping_path = os.path.join(self.models_dir, f"{model_name}_label_mapping.json")
        label_service.save_mapping(mapping_path)

        # Update registry
        self._register_model(model_name, label_service.num_classes)

        logging.info(f"CuRe pre-trained model imported: {model_name} ({label_service.num_classes} classes)")
        return {
            "model_name": model_name,
            "num_classes": label_service.num_classes,
            "model_path": dest_model,
            "mapping_path": mapping_path,
        }

    def _register_model(self, model_name: str, num_classes: int, accuracy: float = 0.0, epochs: int = 0):
        """Add a model to the registry."""
        import datetime
        registry_path = os.path.join(self.models_dir, "registry.json")
        registry = []
        if os.path.exists(registry_path):
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)

        # Remove existing entry with same name
        registry = [m for m in registry if m.get("name") != model_name]

        registry.append({
            "name": model_name,
            "created": datetime.datetime.now().isoformat(),
            "num_classes": num_classes,
            "accuracy": accuracy,
            "epochs": epochs,
        })

        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)


# Global handler instance
cure_handler = CuReHandler()
