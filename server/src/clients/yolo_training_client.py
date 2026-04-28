"""
YOLO Training Client - Handles YOLOv8 model training and inference.
"""

import os
import logging
import re
import time
import base64
import json
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Callable
from datetime import datetime
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)

# Data paths - use STORAGE_PATH for consistency with other services
_storage_path = os.environ.get("STORAGE_PATH", "data")
DATA_ROOT = Path(os.environ.get("YOLO_DATA_PATH", os.path.join(_storage_path, "yolo"))).resolve()
DATASETS_PATH = DATA_ROOT / "datasets"
MODELS_PATH = DATA_ROOT / "models"
BASE_MODELS_PATH = DATA_ROOT / "base_models"
TRAINING_RUNS_PATH = DATA_ROOT / "runs"
PDF_IMAGES_PATH = DATA_ROOT / "pdf_images"

# Ensure directories exist
for path in [DATASETS_PATH, MODELS_PATH, BASE_MODELS_PATH, TRAINING_RUNS_PATH, PDF_IMAGES_PATH]:
    path.mkdir(parents=True, exist_ok=True)

# Default classes for dictionary layout
DEFAULT_CLASSES = ["entry", "subentry", "guidewords", "page_number", "root_index"]

# Default color palette for classes (cycles if more classes than colors)
DEFAULT_CLASS_COLORS = [
    "#0000FF",  # Blue
    "#00FFFF",  # Cyan
    "#808080",  # Gray
    "#FF6600",  # Orange
    "#9C27B0",  # Purple
    "#00FF00",  # Green
    "#FF0000",  # Red
    "#FFFF00",  # Yellow
    "#FF69B4",  # Pink
    "#00BCD4",  # Teal
]

# Base models available
BASE_MODELS = {
    "yolov8n.pt": "YOLOv8 Nano (fastest)",
    "yolov8s.pt": "YOLOv8 Small (recommended)",
    "yolov8m.pt": "YOLOv8 Medium",
    "yolov8l.pt": "YOLOv8 Large",
    "yolov8x.pt": "YOLOv8 XLarge (most accurate)",
}

# Minimum requirements for production training
MIN_TRAINING_IMAGES = 40      # Need 40+ train images (aim for 50+ total with val)
MIN_VAL_IMAGES = 10           # Need 10+ validation images (20% of dataset)
MIN_INSTANCES_PER_CLASS = 20  # Need 20+ annotations per class for reliable detection


class YoloTrainingClient:
    """Client for YOLO model training and inference."""

    def __init__(self):
        self._model_cache: Dict[str, any] = {}
        self._training_callbacks: Dict[str, Callable] = {}

    # ============== Dataset Management ==============

    def create_dataset(self, name: str, classes: List[str], description: str = None) -> Dict:
        """Create a new dataset directory structure."""
        dataset_path = DATASETS_PATH / name

        if dataset_path.exists():
            raise ValueError(f"Dataset '{name}' already exists")

        # Create directory structure
        (dataset_path / "images" / "train").mkdir(parents=True)
        (dataset_path / "images" / "val").mkdir(parents=True)
        (dataset_path / "labels" / "train").mkdir(parents=True)
        (dataset_path / "labels" / "val").mkdir(parents=True)

        # Create dataset.yaml
        yaml_content = f"""# YOLO Dataset Configuration
path: {dataset_path.as_posix()}
train: images/train
val: images/val

# Classes
names:
"""
        for i, cls_name in enumerate(classes):
            yaml_content += f"  {i}: {cls_name}\n"

        yaml_content += f"\n# Number of classes\nnc: {len(classes)}\n"

        with open(dataset_path / "dataset.yaml", "w", encoding="utf-8") as f:
            f.write(yaml_content)

        # Create labels.txt for annotation tools
        with open(dataset_path / "labels.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(classes))

        # Create metadata.json
        metadata = {
            "name": name,
            "description": description or "",
            "classes": [
                {"id": i, "name": c, "color": DEFAULT_CLASS_COLORS[i % len(DEFAULT_CLASS_COLORS)]}
                for i, c in enumerate(classes)
            ],
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        with open(dataset_path / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Created dataset '{name}' with {len(classes)} classes")

        return {
            "dataset_id": name,
            "name": name,
            "classes": metadata["classes"],
            "path": str(dataset_path),
        }

    def add_classes_to_dataset(self, dataset_name: str, new_classes: List[str]) -> Dict:
        """Add new classes to an existing dataset. Skips classes that already exist."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Load current metadata
        metadata_path = dataset_path / "metadata.json"
        with open(metadata_path) as f:
            metadata = json.load(f)

        existing_names = [c["name"] for c in metadata["classes"]]
        added = []
        for cls_name in new_classes:
            if isinstance(cls_name, dict):
                name = cls_name.get("name", "").strip()
                color = cls_name.get("color")
            else:
                name = cls_name.strip()
                color = None
            if name and name not in existing_names:
                new_id = len(metadata["classes"])
                if not color:
                    color = DEFAULT_CLASS_COLORS[new_id % len(DEFAULT_CLASS_COLORS)]
                metadata["classes"].append({"id": new_id, "name": name, "color": color})
                existing_names.append(name)
                added.append(name)

        if not added:
            return {
                "dataset_id": dataset_name,
                "classes": metadata["classes"],
                "added": [],
                "message": "No new classes to add (all already exist)",
            }

        metadata["updated_at"] = datetime.utcnow().isoformat()

        # Update metadata.json
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        # Rebuild dataset.yaml
        all_classes = [c["name"] for c in metadata["classes"]]
        yaml_content = f"""# YOLO Dataset Configuration
path: {dataset_path.as_posix()}
train: images/train
val: images/val

# Classes
names:
"""
        for i, cls_name in enumerate(all_classes):
            yaml_content += f"  {i}: {cls_name}\n"
        yaml_content += f"\n# Number of classes\nnc: {len(all_classes)}\n"

        with open(dataset_path / "dataset.yaml", "w", encoding="utf-8") as f:
            f.write(yaml_content)

        # Rebuild labels.txt
        with open(dataset_path / "labels.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(all_classes))

        logger.info(f"Added {len(added)} classes to dataset '{dataset_name}': {added}")

        return {
            "dataset_id": dataset_name,
            "classes": metadata["classes"],
            "added": added,
            "message": f"Added {len(added)} class(es): {', '.join(added)}",
        }

    def delete_class_from_dataset(self, dataset_name: str, class_id: int) -> Dict:
        """Delete a class from a dataset. Removes all annotations with that class and re-indexes remaining classes."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Load current metadata
        metadata_path = dataset_path / "metadata.json"
        with open(metadata_path) as f:
            metadata = json.load(f)

        # Find the class to delete
        class_to_delete = None
        for cls in metadata["classes"]:
            if cls["id"] == class_id:
                class_to_delete = cls
                break

        if not class_to_delete:
            raise ValueError(f"Class with id {class_id} not found in dataset '{dataset_name}'")

        deleted_name = class_to_delete["name"]
        old_id = class_to_delete["id"]

        # Remove the class and re-index
        metadata["classes"] = [c for c in metadata["classes"] if c["id"] != class_id]
        for i, cls in enumerate(metadata["classes"]):
            cls["id"] = i

        metadata["updated_at"] = datetime.utcnow().isoformat()

        # Update label files: remove annotations with the deleted class and re-map class indices
        for split in ["train", "val"]:
            labels_dir = dataset_path / "labels" / split
            if not labels_dir.exists():
                continue
            for label_file in labels_dir.glob("*.txt"):
                lines = label_file.read_text().strip().split("\n")
                new_lines = []
                for line in lines:
                    if not line.strip():
                        continue
                    parts = line.strip().split()
                    line_class_id = int(parts[0])
                    if line_class_id == old_id:
                        continue  # Remove annotations of deleted class
                    # Re-map class index
                    if line_class_id > old_id:
                        parts[0] = str(line_class_id - 1)
                    new_lines.append(" ".join(parts))
                label_file.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))

        # Update metadata.json
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        # Rebuild dataset.yaml
        all_classes = [c["name"] for c in metadata["classes"]]
        yaml_content = f"""# YOLO Dataset Configuration
path: {dataset_path.as_posix()}
train: images/train
val: images/val

# Classes
names:
"""
        for i, cls_name in enumerate(all_classes):
            yaml_content += f"  {i}: {cls_name}\n"
        yaml_content += f"\n# Number of classes\nnc: {len(all_classes)}\n"

        with open(dataset_path / "dataset.yaml", "w", encoding="utf-8") as f:
            f.write(yaml_content)

        # Rebuild labels.txt
        with open(dataset_path / "labels.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(all_classes))

        logger.info(f"Deleted class '{deleted_name}' (id={class_id}) from dataset '{dataset_name}'")

        return {
            "dataset_id": dataset_name,
            "classes": metadata["classes"],
            "deleted": deleted_name,
            "message": f"Deleted class '{deleted_name}' and updated annotations",
        }

    def update_class_color(self, dataset_name: str, class_id: int, color: str) -> Dict:
        """Update the color of an existing class in a dataset."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        metadata_path = dataset_path / "metadata.json"
        with open(metadata_path) as f:
            metadata = json.load(f)

        # Find the class by id
        found = False
        for cls in metadata["classes"]:
            if cls["id"] == class_id:
                cls["color"] = color
                found = True
                break

        if not found:
            raise ValueError(f"Class with id {class_id} not found in dataset '{dataset_name}'")

        metadata["updated_at"] = datetime.utcnow().isoformat()

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Updated color for class {class_id} in dataset '{dataset_name}' to {color}")

        return {
            "dataset_id": dataset_name,
            "classes": metadata["classes"],
        }

    def update_dataset_metadata(self, dataset_name: str, name: str = None, description: str = None, curated: bool = None) -> Dict:
        """Update dataset name, description, and/or curated flag in metadata.json."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        metadata_path = dataset_path / "metadata.json"
        with open(metadata_path) as f:
            metadata = json.load(f)

        if name is not None:
            metadata["name"] = name.strip()
        if description is not None:
            metadata["description"] = description.strip()
        if curated is not None:
            metadata["curated"] = curated

        metadata["updated_at"] = datetime.utcnow().isoformat()

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Updated metadata for dataset '{dataset_name}'")

        return {
            "dataset_id": dataset_name,
            "name": metadata["name"],
            "description": metadata.get("description", ""),
            "curated": metadata.get("curated", False),
        }

    def rename_class(self, dataset_name: str, class_id: int, new_name: str) -> Dict:
        """Rename an existing class in a dataset. Updates metadata.json, dataset.yaml, and labels.txt."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Class name cannot be empty")

        metadata_path = dataset_path / "metadata.json"
        with open(metadata_path) as f:
            metadata = json.load(f)

        # Check for duplicate name
        for cls in metadata["classes"]:
            if cls["name"] == new_name and cls["id"] != class_id:
                raise ValueError(f"Class name '{new_name}' already exists")

        # Find and rename
        old_name = None
        for cls in metadata["classes"]:
            if cls["id"] == class_id:
                old_name = cls["name"]
                cls["name"] = new_name
                # Ensure color is persisted (older datasets may lack it)
                if "color" not in cls:
                    cls["color"] = DEFAULT_CLASS_COLORS[cls["id"] % len(DEFAULT_CLASS_COLORS)]
                break

        if old_name is None:
            raise ValueError(f"Class with id {class_id} not found in dataset '{dataset_name}'")

        metadata["updated_at"] = datetime.utcnow().isoformat()

        # Update metadata.json
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        # Rebuild dataset.yaml
        all_classes = [c["name"] for c in metadata["classes"]]
        yaml_content = f"""# YOLO Dataset Configuration
path: {dataset_path.as_posix()}
train: images/train
val: images/val

# Classes
names:
"""
        for i, cls_name in enumerate(all_classes):
            yaml_content += f"  {i}: {cls_name}\n"
        yaml_content += f"\n# Number of classes\nnc: {len(all_classes)}\n"

        with open(dataset_path / "dataset.yaml", "w", encoding="utf-8") as f:
            f.write(yaml_content)

        # Rebuild labels.txt
        with open(dataset_path / "labels.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(all_classes))

        logger.info(f"Renamed class {class_id} in dataset '{dataset_name}': '{old_name}' -> '{new_name}'")

        return {
            "dataset_id": dataset_name,
            "classes": metadata["classes"],
            "old_name": old_name,
            "new_name": new_name,
        }

    def add_image_to_dataset(
        self,
        dataset_name: str,
        image_base64: str,
        filename: str,
        annotations: List[Dict],
        split: str = "train"
    ) -> Dict:
        """Add an image and its annotations to a dataset."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        if split not in ["train", "val"]:
            raise ValueError(f"Invalid split: {split}. Must be 'train' or 'val'")

        # Decode and save image
        image_data = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_data))

        # Generate unique filename if needed
        base_name = Path(filename).stem
        ext = Path(filename).suffix or ".png"
        image_path = dataset_path / "images" / split / f"{base_name}{ext}"

        # Handle duplicate filenames
        counter = 1
        while image_path.exists():
            image_path = dataset_path / "images" / split / f"{base_name}_{counter}{ext}"
            counter += 1

        # Save image
        image.save(image_path)

        # Save annotations in YOLO format
        label_path = dataset_path / "labels" / split / f"{image_path.stem}.txt"
        with open(label_path, "w", encoding="utf-8") as f:
            for ann in annotations:
                line = f"{ann['class_id']} {ann['x_center']:.6f} {ann['y_center']:.6f} {ann['width']:.6f} {ann['height']:.6f}\n"
                f.write(line)

        # Update metadata
        self._update_dataset_metadata(dataset_name)

        logger.info(f"Added image '{image_path.name}' to dataset '{dataset_name}' ({split})")

        return {
            "image_id": image_path.stem,
            "filename": image_path.name,
            "annotation_count": len(annotations),
            "split": split,
        }

    def get_dataset_stats(self, dataset_name: str) -> Dict:
        """Get statistics about a dataset."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Load metadata
        with open(dataset_path / "metadata.json") as f:
            metadata = json.load(f)

        # Backfill missing colors from palette and persist
        dirty = False
        for i, cls in enumerate(metadata["classes"]):
            if not cls.get("color"):
                cls["color"] = DEFAULT_CLASS_COLORS[i % len(DEFAULT_CLASS_COLORS)]
                dirty = True
        if dirty:
            with open(dataset_path / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

        # Count images
        train_images = list((dataset_path / "images" / "train").glob("*"))
        val_images = list((dataset_path / "images" / "val").glob("*"))
        train_images = [f for f in train_images if f.suffix.lower() in [".png", ".jpg", ".jpeg"]]
        val_images = [f for f in val_images if f.suffix.lower() in [".png", ".jpg", ".jpeg"]]

        # Count annotations per class
        class_distribution = {c["name"]: 0 for c in metadata["classes"]}
        total_annotations = 0

        for split in ["train", "val"]:
            label_dir = dataset_path / "labels" / split
            for label_file in label_dir.glob("*.txt"):
                with open(label_file) as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            class_id = int(parts[0])
                            if class_id < len(metadata["classes"]):
                                class_name = metadata["classes"][class_id]["name"]
                                class_distribution[class_name] += 1
                                total_annotations += 1

        # Check readiness for training
        warnings = []
        total_images = len(train_images) + len(val_images)

        if len(train_images) < MIN_TRAINING_IMAGES:
            warnings.append(f"Recommended: {MIN_TRAINING_IMAGES}+ training images (have {len(train_images)})")

        if len(val_images) < MIN_VAL_IMAGES:
            warnings.append(f"Recommended: {MIN_VAL_IMAGES}+ validation images (have {len(val_images)})")

        for class_name, count in class_distribution.items():
            if count < MIN_INSTANCES_PER_CLASS:
                warnings.append(f"Recommended: {MIN_INSTANCES_PER_CLASS}+ instances for '{class_name}' (have {count})")

        # Only block training if there are literally no images or no annotations
        can_train = len(train_images) > 0 and total_annotations > 0

        # Compute curated status from per-image tracking
        curated_images = set(metadata.get("curated_images", []))
        curated_count = len(curated_images)
        all_curated = total_images > 0 and curated_count >= total_images

        return {
            "dataset_id": dataset_name,
            "name": metadata["name"],
            "description": metadata.get("description", ""),
            "classes": metadata["classes"],
            "total_images": total_images,
            "train_images": len(train_images),
            "val_images": len(val_images),
            "total_annotations": total_annotations,
            "class_distribution": class_distribution,
            "ready_for_training": can_train,
            "curated": all_curated,
            "curated_count": curated_count,
            "warnings": warnings,
            "issues": warnings,
        }

    def list_datasets(self) -> List[Dict]:
        """List all available datasets."""
        datasets = []

        for dataset_dir in DATASETS_PATH.iterdir():
            if dataset_dir.is_dir() and (dataset_dir / "metadata.json").exists():
                with open(dataset_dir / "metadata.json") as f:
                    metadata = json.load(f)

                # Backfill missing colors
                dirty = False
                for i, cls in enumerate(metadata.get("classes", [])):
                    if not cls.get("color"):
                        cls["color"] = DEFAULT_CLASS_COLORS[i % len(DEFAULT_CLASS_COLORS)]
                        dirty = True
                if dirty:
                    with open(dataset_dir / "metadata.json", "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=2)

                # Count images
                train_count = len(list((dataset_dir / "images" / "train").glob("*")))
                val_count = len(list((dataset_dir / "images" / "val").glob("*")))

                total_count = train_count + val_count
                curated_images = set(metadata.get("curated_images", []))
                all_curated = total_count > 0 and len(curated_images) >= total_count

                datasets.append({
                    "dataset_id": dataset_dir.name,
                    "name": metadata.get("name", dataset_dir.name),
                    "description": metadata.get("description", ""),
                    "class_count": len(metadata.get("classes", [])),
                    "image_count": total_count,
                    "train_images": train_count,
                    "val_images": val_count,
                    "classes": metadata.get("classes", []),
                    "curated": all_curated,
                    "curated_count": len(curated_images),
                    "created_at": metadata.get("created_at"),
                    "updated_at": metadata.get("updated_at"),
                })

        return sorted(datasets, key=lambda x: x.get("updated_at", ""), reverse=True)

    def merge_datasets(self, source_names: List[str], target_name: str, description: str = None) -> Dict:
        """
        Merge multiple datasets into a new one. Originals stay untouched.
        Classes are merged by name; label class IDs are remapped accordingly.
        """
        # Validate sources
        source_paths = []
        source_metadatas = []
        for name in source_names:
            path = DATASETS_PATH / name
            if not path.exists():
                raise ValueError(f"Source dataset '{name}' not found")
            with open(path / "metadata.json", encoding="utf-8") as f:
                source_metadatas.append(json.load(f))
            source_paths.append(path)

        # Validate target doesn't exist
        target_path = DATASETS_PATH / target_name
        if target_path.exists():
            raise ValueError(f"Dataset '{target_name}' already exists")

        # Build merged class list (union by name, preserving order)
        merged_classes = []
        class_name_to_id = {}
        for meta in source_metadatas:
            for cls in meta.get("classes", []):
                if cls["name"] not in class_name_to_id:
                    new_id = len(merged_classes)
                    class_name_to_id[cls["name"]] = new_id
                    merged_classes.append({
                        "id": new_id,
                        "name": cls["name"],
                        "color": cls.get("color", DEFAULT_CLASS_COLORS[new_id % len(DEFAULT_CLASS_COLORS)])
                    })

        # Build per-source class ID remap: source_class_id -> target_class_id
        remaps = []
        for meta in source_metadatas:
            remap = {}
            for cls in meta.get("classes", []):
                remap[cls["id"]] = class_name_to_id[cls["name"]]
            remaps.append(remap)

        # Create target dataset structure
        class_names = [c["name"] for c in merged_classes]
        self.create_dataset(target_name, class_names, description or f"Merged from: {', '.join(source_names)}")

        # Overwrite metadata with merged classes (to keep colors)
        target_meta_path = target_path / "metadata.json"
        with open(target_meta_path, encoding="utf-8") as f:
            target_metadata = json.load(f)
        target_metadata["classes"] = merged_classes

        # Copy images and remap labels
        total_images = 0
        merged_curated = set()
        used_filenames = {"train": set(), "val": set()}

        for src_idx, (src_path, src_meta, remap) in enumerate(zip(source_paths, source_metadatas, remaps)):
            src_curated = set(src_meta.get("curated_images", []))

            for split in ["train", "val"]:
                img_dir = src_path / "images" / split
                lbl_dir = src_path / "labels" / split
                if not img_dir.exists():
                    continue

                for img_file in img_dir.iterdir():
                    if not img_file.is_file():
                        continue

                    # Handle filename collisions
                    stem = img_file.stem
                    suffix = img_file.suffix
                    final_stem = stem
                    if final_stem in used_filenames[split]:
                        # Prefix with source dataset name
                        final_stem = f"{source_names[src_idx]}_{stem}"
                    counter = 2
                    while final_stem in used_filenames[split]:
                        final_stem = f"{source_names[src_idx]}_{stem}_{counter}"
                        counter += 1
                    used_filenames[split].add(final_stem)

                    # Copy image
                    target_img = target_path / "images" / split / f"{final_stem}{suffix}"
                    shutil.copy2(img_file, target_img)

                    # Copy and remap label
                    label_file = lbl_dir / f"{stem}.txt"
                    if label_file.exists():
                        with open(label_file, "r", encoding="utf-8") as f:
                            lines = f.readlines()

                        remapped_lines = []
                        for line in lines:
                            parts = line.strip().split()
                            if len(parts) >= 5:
                                old_class_id = int(parts[0])
                                new_class_id = remap.get(old_class_id, old_class_id)
                                remapped_lines.append(f"{new_class_id} {' '.join(parts[1:])}\n")

                        target_label = target_path / "labels" / split / f"{final_stem}.txt"
                        with open(target_label, "w", encoding="utf-8") as f:
                            f.writelines(remapped_lines)

                    # Track curated status
                    if stem in src_curated:
                        merged_curated.add(final_stem)

                    total_images += 1

        # Update metadata with curated images
        target_metadata["curated_images"] = sorted(merged_curated)
        with open(target_meta_path, "w", encoding="utf-8") as f:
            json.dump(target_metadata, f, indent=2, ensure_ascii=False)

        # Update labels.txt
        with open(target_path / "labels.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(class_names))

        logger.info(f"Merged {len(source_names)} datasets into '{target_name}': {total_images} images, {len(merged_classes)} classes")

        return {
            "success": True,
            "dataset_id": target_name,
            "total_images": total_images,
            "sources_merged": len(source_names),
            "class_count": len(merged_classes),
        }

    def delete_dataset(self, dataset_name: str) -> bool:
        """Delete a dataset."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        shutil.rmtree(dataset_path)
        logger.info(f"Deleted dataset '{dataset_name}'")
        return True

    def _update_dataset_metadata(self, dataset_name: str):
        """Update dataset metadata timestamp."""
        metadata_path = DATASETS_PATH / dataset_name / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
            metadata["updated_at"] = datetime.utcnow().isoformat()
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

    def list_dataset_images(self, dataset_name: str) -> List[Dict]:
        """List all images in a dataset with their annotation counts."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Load curated set from metadata
        metadata_path = dataset_path / "metadata.json"
        curated_images = set()
        if metadata_path.exists():
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)
                curated_images = set(metadata.get("curated_images", []))

        images = []

        for split in ["train", "val"]:
            images_dir = dataset_path / "images" / split
            labels_dir = dataset_path / "labels" / split

            for image_file in images_dir.glob("*"):
                if image_file.suffix.lower() not in [".png", ".jpg", ".jpeg"]:
                    continue

                label_file = labels_dir / f"{image_file.stem}.txt"
                annotation_count = 0

                if label_file.exists():
                    with open(label_file) as f:
                        lines = [l.strip() for l in f.readlines() if l.strip()]
                        annotation_count = len(lines)

                images.append({
                    "image_id": image_file.stem,
                    "filename": image_file.name,
                    "split": split,
                    "annotation_count": annotation_count,
                    "has_annotations": annotation_count > 0,
                    "curated": image_file.stem in curated_images,
                })

        return sorted(images, key=lambda x: (x["split"], x["filename"]))

    def get_dataset_image(self, dataset_name: str, image_id: str, split: str = None) -> Dict:
        """Get a specific image with its annotations from the dataset."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Load dataset metadata for class names and curated set
        metadata_path = dataset_path / "metadata.json"
        class_names = {}
        curated_images = set()
        if metadata_path.exists():
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)
                for cls in metadata.get("classes", []):
                    class_names[cls["id"]] = cls["name"]
                curated_images = set(metadata.get("curated_images", []))

        # Search for the image in train/val splits
        splits_to_check = [split] if split else ["train", "val"]

        for check_split in splits_to_check:
            images_dir = dataset_path / "images" / check_split
            labels_dir = dataset_path / "labels" / check_split

            # Find image file (could be .png, .jpg, .jpeg)
            image_file = None
            for ext in [".png", ".jpg", ".jpeg"]:
                candidate = images_dir / f"{image_id}{ext}"
                if candidate.exists():
                    image_file = candidate
                    break

            if not image_file:
                continue

            # Read image as base64
            with open(image_file, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # Get image dimensions
            img = Image.open(image_file)
            img_width, img_height = img.size

            # Read annotations
            annotations = []
            label_file = labels_dir / f"{image_id}.txt"
            if label_file.exists():
                with open(label_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split()
                        if len(parts) >= 5:
                            class_id = int(parts[0])
                            annotations.append({
                                "class_id": class_id,
                                "class_name": class_names.get(class_id, f"class_{class_id}"),
                                "x_center": float(parts[1]),
                                "y_center": float(parts[2]),
                                "width": float(parts[3]),
                                "height": float(parts[4]),
                            })

            return {
                "image_id": image_id,
                "filename": image_file.name,
                "split": check_split,
                "image_base64": image_data,
                "image_width": img_width,
                "image_height": img_height,
                "annotations": annotations,
                "annotation_count": len(annotations),
                "curated": image_id in curated_images,
            }

        raise ValueError(f"Image '{image_id}' not found in dataset '{dataset_name}'")

    def toggle_image_curated(self, dataset_name: str, image_id: str, curated: bool) -> Dict:
        """Mark or unmark an image as curated in the dataset metadata."""
        dataset_path = DATASETS_PATH / dataset_name
        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        metadata_path = dataset_path / "metadata.json"
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)

        curated_images = set(metadata.get("curated_images", []))

        if curated:
            curated_images.add(image_id)
        else:
            curated_images.discard(image_id)

        metadata["curated_images"] = sorted(curated_images)
        metadata["updated_at"] = datetime.utcnow().isoformat()

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return {
            "image_id": image_id,
            "curated": curated,
            "curated_count": len(curated_images),
        }

    def update_image_annotations(self, dataset_name: str, image_id: str, annotations: List[Dict], split: str = None) -> Dict:
        """Update annotations for an existing image in the dataset."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Find the image and its label file
        splits_to_check = [split] if split else ["train", "val"]

        for check_split in splits_to_check:
            images_dir = dataset_path / "images" / check_split
            labels_dir = dataset_path / "labels" / check_split

            # Find image file
            image_file = None
            for ext in [".png", ".jpg", ".jpeg"]:
                candidate = images_dir / f"{image_id}{ext}"
                if candidate.exists():
                    image_file = candidate
                    break

            if not image_file:
                continue

            # Write updated annotations to label file
            label_file = labels_dir / f"{image_id}.txt"
            with open(label_file, "w", encoding="utf-8") as f:
                for ann in annotations:
                    class_id = ann.get("class_id", 0)
                    x_center = ann.get("x_center", 0)
                    y_center = ann.get("y_center", 0)
                    width = ann.get("width", 0)
                    height = ann.get("height", 0)
                    f.write(f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}\n")

            logger.info(f"Updated annotations for {image_id}: {len(annotations)} annotations")

            self._update_dataset_metadata(dataset_name)

            return {
                "image_id": image_id,
                "split": check_split,
                "annotation_count": len(annotations),
            }

        raise ValueError(f"Image '{image_id}' not found in dataset '{dataset_name}'")

    def delete_dataset_image(self, dataset_name: str, image_id: str) -> bool:
        """Delete a specific image and its label file from a dataset."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        deleted = False

        for split in ["train", "val"]:
            images_dir = dataset_path / "images" / split
            labels_dir = dataset_path / "labels" / split

            # Find and delete image
            for ext in [".png", ".jpg", ".jpeg"]:
                image_file = images_dir / f"{image_id}{ext}"
                if image_file.exists():
                    image_file.unlink()
                    deleted = True
                    logger.info(f"Deleted image: {image_file}")
                    break

            # Delete label file
            label_file = labels_dir / f"{image_id}.txt"
            if label_file.exists():
                label_file.unlink()
                logger.info(f"Deleted label: {label_file}")

        if not deleted:
            raise ValueError(f"Image '{image_id}' not found in dataset '{dataset_name}'")

        self._update_dataset_metadata(dataset_name)
        return True

    def cleanup_empty_images(self, dataset_name: str) -> Dict:
        """Remove all images that have no annotations (empty label files)."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        removed_count = 0
        removed_images = []

        for split in ["train", "val"]:
            images_dir = dataset_path / "images" / split
            labels_dir = dataset_path / "labels" / split

            for image_file in list(images_dir.glob("*")):
                if image_file.suffix.lower() not in [".png", ".jpg", ".jpeg"]:
                    continue

                label_file = labels_dir / f"{image_file.stem}.txt"

                # Check if label file is empty or missing
                has_annotations = False
                if label_file.exists():
                    with open(label_file) as f:
                        lines = [l.strip() for l in f.readlines() if l.strip()]
                        has_annotations = len(lines) > 0

                if not has_annotations:
                    # Delete image and label
                    image_file.unlink()
                    if label_file.exists():
                        label_file.unlink()
                    removed_images.append(image_file.name)
                    removed_count += 1
                    logger.info(f"Removed empty image: {image_file}")

        self._update_dataset_metadata(dataset_name)

        return {
            "removed_count": removed_count,
            "removed_images": removed_images,
        }

    # ============== Model Management ==============

    def list_models(self) -> Dict:
        """List all trained models and available base models."""
        models = []

        # List trained models
        for model_dir in MODELS_PATH.iterdir():
            if model_dir.is_dir() and (model_dir / "metadata.json").exists():
                with open(model_dir / "metadata.json") as f:
                    metadata = json.load(f)

                model_file = model_dir / "best.pt"
                file_size = model_file.stat().st_size / (1024 * 1024) if model_file.exists() else 0

                models.append({
                    "model_id": model_dir.name,
                    "name": metadata.get("name", model_dir.name),
                    "base_model": metadata.get("base_model", "unknown"),
                    "dataset_name": metadata.get("dataset_name", "unknown"),
                    "classes": metadata.get("classes", []),
                    "metrics": metadata.get("metrics"),
                    "created_at": metadata.get("created_at"),
                    "training_epochs": metadata.get("training_epochs", 0),
                    "training_config": metadata.get("training_config"),
                    "file_path": str(model_file),
                    "file_size_mb": round(file_size, 2),
                })

        # Sort by creation date
        models = sorted(models, key=lambda x: x.get("created_at", ""), reverse=True)

        # List base models
        base_models = list(BASE_MODELS.keys())

        # Add any custom models that can be used as base
        for model in models:
            if model["model_id"] not in base_models:
                base_models.append(f"{model['model_id']}/best.pt")

        return {
            "models": models,
            "base_models": base_models,
        }

    def get_model_path(self, model_name: str) -> Path:
        """Get the path to a model file."""
        # Check if it's a base model
        if model_name in BASE_MODELS:
            local_path = BASE_MODELS_PATH / model_name
            if local_path.exists():
                return local_path
            # Return just the model name so ultralytics auto-downloads it
            return Path(model_name)

        # Check if it's a trained model
        model_path = MODELS_PATH / model_name / "best.pt"
        if model_path.exists():
            return model_path

        # Check if it's a full path within models
        if "/" in model_name:
            parts = model_name.split("/")
            model_path = MODELS_PATH / parts[0] / parts[1]
            if model_path.exists():
                return model_path

        raise ValueError(f"Model '{model_name}' not found")

    def delete_model(self, model_name: str) -> bool:
        """Delete a trained model."""
        model_path = MODELS_PATH / model_name

        if not model_path.exists():
            raise ValueError(f"Model '{model_name}' not found")

        # Don't allow deleting the active model
        active = self.get_active_model()
        if active and active.get("model_name") == model_name:
            raise ValueError(f"Cannot delete the active model '{model_name}'. Activate a different model first.")

        shutil.rmtree(model_path)
        logger.info(f"Deleted model '{model_name}'")

        # Clear from cache
        if model_name in self._model_cache:
            del self._model_cache[model_name]

        return True

    def activate_model(self, model_name: str) -> Dict:
        """Set a trained model as the active/default model."""
        model_path = MODELS_PATH / model_name / "best.pt"
        if not model_path.exists():
            raise ValueError(f"Model '{model_name}' not found")

        active_file = DATA_ROOT / "active_model.txt"
        active_file.write_text(model_name)
        logger.info(f"Activated YOLO model '{model_name}'")

        return {"success": True, "model_name": model_name}

    def get_active_model(self) -> Optional[Dict]:
        """Get the currently active model. Returns None if no model is active."""
        active_file = DATA_ROOT / "active_model.txt"

        if active_file.exists():
            model_name = active_file.read_text().strip()
            model_path = MODELS_PATH / model_name / "best.pt"
            if model_path.exists():
                return {"active": True, "model_name": model_name}

        # Fallback: use the most recently trained model
        models = self.list_models()
        if models["models"]:
            return {"active": True, "model_name": models["models"][0]["model_id"]}

        return {"active": False, "model_name": None}

    # ============== Training ==============

    def train_model(
        self,
        dataset_name: str,
        output_name: str,
        base_model: str = "yolov8s.pt",
        config: Dict = None,
        progress_callback: Callable = None
    ) -> Dict:
        """
        Train a YOLO model on a dataset.

        Args:
            dataset_name: Name of the dataset to train on
            output_name: Name for the output model
            base_model: Base model to fine-tune (e.g., 'yolov8s.pt' or 'ahw_v1/best.pt')
            config: Training configuration dict
            progress_callback: Optional callback for progress updates

        Returns:
            Dict with training results
        """
        from ultralytics import YOLO

        dataset_path = DATASETS_PATH / dataset_name
        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Get dataset stats to validate (warnings are non-blocking)
        stats = self.get_dataset_stats(dataset_name)
        if not stats["ready_for_training"]:
            raise ValueError("Dataset has no training images or annotations")

        # Resolve base model path
        if base_model in BASE_MODELS:
            base_model_path = base_model  # YOLO will download if needed
        else:
            base_model_path = str(self.get_model_path(base_model))

        # Default config
        default_config = {
            "epochs": 100,
            "batch_size": 4,
            "image_size": 1024,
            "patience": 20,
            "device": "auto",
            "workers": 4,
            "flipud": 0.0,
            "fliplr": 0.0,
            "mosaic": 0.0,
        }
        if config:
            default_config.update(config)

        config = default_config

        # Prepare output directory
        output_dir = MODELS_PATH / output_name
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting training: dataset={dataset_name}, base={base_model}, output={output_name}")

        # Load base model
        model = YOLO(base_model_path)

        # Determine device
        device = config["device"]
        if device == "auto":
            import torch
            device = "0" if torch.cuda.is_available() else "cpu"

        # Train
        start_time = time.time()
        total_epochs = config["epochs"]

        # Register epoch-end callback to report progress
        if progress_callback:
            def on_train_epoch_end(trainer):
                epoch = trainer.epoch + 1  # 0-indexed → 1-indexed
                progress_pct = round((epoch / total_epochs) * 100, 1)
                metrics = {}
                if hasattr(trainer, "metrics") and trainer.metrics:
                    metrics = {
                        "mAP50": trainer.metrics.get("metrics/mAP50(B)", 0),
                        "mAP50-95": trainer.metrics.get("metrics/mAP50-95(B)", 0),
                        "precision": trainer.metrics.get("metrics/precision(B)", 0),
                        "recall": trainer.metrics.get("metrics/recall(B)", 0),
                    }
                elapsed = time.time() - start_time
                eta = int((elapsed / epoch) * (total_epochs - epoch)) if epoch > 0 else None
                progress_callback(epoch, total_epochs, progress_pct, metrics, eta)

            model.add_callback("on_train_epoch_end", on_train_epoch_end)

        results = model.train(
            data=str(dataset_path / "dataset.yaml"),
            epochs=total_epochs,
            batch=config["batch_size"],
            imgsz=config["image_size"],
            patience=config["patience"],
            device=device,
            workers=config["workers"],
            flipud=config["flipud"],
            fliplr=config["fliplr"],
            mosaic=config["mosaic"],
            project=str(TRAINING_RUNS_PATH),
            name=output_name,
            exist_ok=True,
            verbose=True,
        )

        training_time = time.time() - start_time

        # Copy best weights to models directory
        runs_best = TRAINING_RUNS_PATH / output_name / "weights" / "best.pt"
        if runs_best.exists():
            shutil.copy(runs_best, output_dir / "best.pt")
            shutil.copy(TRAINING_RUNS_PATH / output_name / "weights" / "last.pt", output_dir / "last.pt")

        # Extract metrics
        metrics = {}
        if hasattr(results, "results_dict"):
            metrics = {
                "mAP50": results.results_dict.get("metrics/mAP50(B)", 0),
                "mAP50-95": results.results_dict.get("metrics/mAP50-95(B)", 0),
                "precision": results.results_dict.get("metrics/precision(B)", 0),
                "recall": results.results_dict.get("metrics/recall(B)", 0),
            }

        # Determine actual epochs trained (may be less than config due to early stopping)
        actual_epochs = config["epochs"]
        results_csv = TRAINING_RUNS_PATH / output_name / "results.csv"
        if results_csv.exists():
            try:
                with open(results_csv, "r") as f:
                    actual_epochs = sum(1 for line in f) - 1  # subtract header
            except Exception:
                pass

        # Save metadata
        metadata = {
            "name": output_name,
            "base_model": base_model,
            "dataset_name": dataset_name,
            "classes": stats["classes"],
            "metrics": metrics,
            "created_at": datetime.utcnow().isoformat(),
            "training_epochs": actual_epochs,
            "training_config": config,
            "training_time_seconds": training_time,
        }
        with open(output_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Training complete: {output_name}, mAP50={metrics.get('mAP50', 0):.3f}")

        return {
            "success": True,
            "model_id": output_name,
            "metrics": metrics,
            "training_time_seconds": training_time,
            "model_path": str(output_dir / "best.pt"),
            "actual_epochs": actual_epochs,
        }

    # ============== Inference ==============

    def predict(
        self,
        image_base64: str,
        model_name: str = "default",
        confidence: float = 0.25,
        iou: float = 0.45
    ) -> Dict:
        """
        Run inference on an image.

        Args:
            image_base64: Base64 encoded image
            model_name: Model to use ('default' uses first available trained model)
            confidence: Confidence threshold
            iou: IoU threshold for NMS

        Returns:
            Dict with detections
        """
        from ultralytics import YOLO

        start_time = time.time()

        # Decode image
        image_data = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_data))
        img_width, img_height = image.size

        # Get model
        if model_name == "default":
            active = self.get_active_model()
            if active and active.get("model_name"):
                model_name = active["model_name"]
            else:
                raise ValueError("No trained models available. Train a model first.")

        # Load model (with caching)
        if model_name not in self._model_cache:
            model_path = self.get_model_path(model_name)
            self._model_cache[model_name] = YOLO(str(model_path))

        model = self._model_cache[model_name]

        # Log device info
        import torch
        device = model.device if hasattr(model, 'device') else 'unknown'
        logger.info(f"YOLO predict: model={model_name}, device={device}, CUDA={torch.cuda.is_available()}, image={img_width}x{img_height}")

        # Run inference
        results = model.predict(
            image,
            conf=confidence,
            iou=iou,
            verbose=False
        )

        # Parse results
        detections = []
        if results and len(results) > 0:
            result = results[0]
            for box in result.boxes:
                x0, y0, x1, y1 = box.xyxy[0].tolist()
                class_id = int(box.cls[0].item())
                class_name = model.names[class_id] if class_id in model.names else f"class_{class_id}"

                detections.append({
                    "class_id": class_id,
                    "class_name": class_name,
                    "confidence": round(box.conf[0].item(), 4),
                    "bbox": {
                        "x": round(x0, 1),
                        "y": round(y0, 1),
                        "width": round(x1 - x0, 1),
                        "height": round(y1 - y0, 1),
                    }
                })

        processing_time = int((time.time() - start_time) * 1000)
        device_used = str(results[0].boxes.data.device) if results and len(results) > 0 and len(results[0].boxes) > 0 else str(device)

        logger.info(f"YOLO predict: {len(detections)} detections in {processing_time}ms, device={device_used}")

        # Load model metadata to include class colors from training
        model_classes = []
        model_dir = MODELS_PATH / model_name
        metadata_path = model_dir / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
            model_classes = metadata.get("classes", [])

        return {
            "success": True,
            "detections": detections,
            "model_used": model_name,
            "model_classes": model_classes,
            "processing_time_ms": processing_time,
            "image_size": {"width": img_width, "height": img_height},
        }

    # ============== Auto-Annotate ==============

    def predict_from_file(
        self,
        image_path: str,
        model_name: str = "default",
        confidence: float = 0.25,
        iou: float = 0.45
    ) -> Dict:
        """
        Run inference on an image file directly from disk (no base64 roundtrip).

        Returns detections with YOLO normalized coordinates plus model class names.
        """
        from ultralytics import YOLO

        image = Image.open(image_path)
        img_width, img_height = image.size

        # Resolve model
        if model_name == "default":
            active = self.get_active_model()
            if active and active.get("model_name"):
                model_name = active["model_name"]
            else:
                raise ValueError("No trained models available.")

        # Load model (with caching)
        if model_name not in self._model_cache:
            model_path = self.get_model_path(model_name)
            self._model_cache[model_name] = YOLO(str(model_path))

        model = self._model_cache[model_name]

        results = model.predict(image, conf=confidence, iou=iou, verbose=False)

        detections = []
        if results and len(results) > 0:
            result = results[0]
            for box in result.boxes:
                x0, y0, x1, y1 = box.xyxy[0].tolist()
                class_id = int(box.cls[0].item())

                # Pixel dimensions
                px_w = x1 - x0
                px_h = y1 - y0

                # YOLO normalized coordinates
                detections.append({
                    "class_id": class_id,
                    "confidence": round(box.conf[0].item(), 4),
                    "x_center": (x0 + px_w / 2) / img_width,
                    "y_center": (y0 + px_h / 2) / img_height,
                    "width": px_w / img_width,
                    "height": px_h / img_height,
                })

        return {
            "detections": detections,
            "model_classes": dict(model.names),
            "image_size": {"width": img_width, "height": img_height},
        }

    def auto_annotate_dataset(
        self,
        source_project_id: str,
        model_name: str,
        dataset_name: str,
        confidence: float = 0.25,
        iou: float = 0.45,
        val_ratio: float = 0.2,
        progress_callback: Optional[Callable] = None,
    ) -> Dict:
        """
        Create a new dataset by running model predictions on all images in a source project.

        Args:
            source_project_id: Project ID from pages handler
            model_name: Trained model to use for predictions
            dataset_name: Name for the new dataset
            confidence: Confidence threshold for predictions
            iou: IoU threshold for NMS
            val_ratio: Fraction of images for validation split (default 0.2)
            progress_callback: Called with (current, total, message) after each image
        """
        import random
        from handlers.pages_handler import PagesHandler

        pages_handler = PagesHandler()

        # 1. Get project and its pages
        project = pages_handler.get_project(source_project_id)
        if project is None:
            raise ValueError(f"Project '{source_project_id}' not found")

        pages = project.pages
        if not pages:
            raise ValueError(f"Project '{source_project_id}' has no images")

        total_images = len(pages)

        # 2. Load model to get class names and colors from model metadata
        from ultralytics import YOLO
        if model_name not in self._model_cache:
            model_path = self.get_model_path(model_name)
            self._model_cache[model_name] = YOLO(str(model_path))
        model = self._model_cache[model_name]
        model_classes = [model.names[i] for i in sorted(model.names.keys())]

        # Load model metadata to preserve training colors
        model_metadata_path = MODELS_PATH / model_name / "metadata.json"
        model_class_colors = {}
        if model_metadata_path.exists():
            with open(model_metadata_path) as f:
                model_meta = json.load(f)
            for cls in model_meta.get("classes", []):
                model_class_colors[cls["name"]] = cls.get("color")

        # 3. Create dataset with the model's classes
        self.create_dataset(
            name=dataset_name,
            classes=model_classes,
            description=f"Auto-annotated from '{project.name}' using model '{model_name}'"
        )

        # Overwrite default colors with model's training colors
        if model_class_colors:
            ds_metadata_path = DATASETS_PATH / dataset_name / "metadata.json"
            with open(ds_metadata_path) as f:
                ds_metadata = json.load(f)
            for cls in ds_metadata["classes"]:
                if cls["name"] in model_class_colors and model_class_colors[cls["name"]]:
                    cls["color"] = model_class_colors[cls["name"]]
            with open(ds_metadata_path, "w", encoding="utf-8") as f:
                json.dump(ds_metadata, f, indent=2)

        # 4. Decide train/val split
        indices = list(range(total_images))
        random.shuffle(indices)
        val_count = max(1, int(total_images * val_ratio))
        val_indices = set(indices[:val_count])

        # 5. Process each image
        dataset_path = DATASETS_PATH / dataset_name
        total_detections = 0
        images_with_detections = 0

        for i, page in enumerate(pages):
            split = "val" if i in val_indices else "train"

            image_path = pages_handler.get_page_path(source_project_id, page.page_number)
            if image_path is None:
                logger.warning(f"Auto-annotate: skipped {page.filename} (file not found)")
                if progress_callback:
                    progress_callback(i + 1, total_images, f"Skipped {page.filename}")
                continue

            try:
                pred_result = self.predict_from_file(
                    image_path=image_path,
                    model_name=model_name,
                    confidence=confidence,
                    iou=iou,
                )

                detections = pred_result["detections"]

                # Copy image file directly (no re-encoding)
                src_path = Path(image_path)
                dest_image_path = dataset_path / "images" / split / page.filename
                counter = 1
                base_stem = dest_image_path.stem
                while dest_image_path.exists():
                    dest_image_path = dataset_path / "images" / split / f"{base_stem}_{counter}{dest_image_path.suffix}"
                    counter += 1

                shutil.copy2(str(src_path), str(dest_image_path))

                # Write YOLO label file
                label_path = dataset_path / "labels" / split / f"{dest_image_path.stem}.txt"
                with open(label_path, "w", encoding="utf-8") as f:
                    for d in detections:
                        f.write(f"{d['class_id']} {d['x_center']:.6f} {d['y_center']:.6f} {d['width']:.6f} {d['height']:.6f}\n")

                total_detections += len(detections)
                if detections:
                    images_with_detections += 1

            except Exception as e:
                logger.error(f"Auto-annotate failed for {page.filename}: {e}")

            if progress_callback:
                progress_callback(i + 1, total_images, f"Processed {page.filename}")

        # 6. Update metadata
        self._update_dataset_metadata(dataset_name)

        return {
            "success": True,
            "dataset_name": dataset_name,
            "source_project": source_project_id,
            "model_used": model_name,
            "total_images": total_images,
            "images_with_detections": images_with_detections,
            "total_detections": total_detections,
            "train_images": total_images - len(val_indices),
            "val_images": len(val_indices),
            "classes": model_classes,
        }

    # ============== Dataset Export ==============

    def export_dataset_zip(self, dataset_name: str) -> str:
        """
        Export a dataset as a portable YOLO training zip.

        Returns path to a temp zip file (caller must delete).
        """
        import zipfile
        import tempfile

        dataset_path = DATASETS_PATH / dataset_name
        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Read metadata for class names
        metadata_path = dataset_path / "metadata.json"
        class_names = []
        if metadata_path.exists():
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)
                class_names = [c["name"] for c in metadata.get("classes", [])]

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix=f"{dataset_name}_training_")
        tmp.close()

        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add images and labels for both splits
            for split in ["train", "val"]:
                for subdir in ["images", "labels"]:
                    split_dir = dataset_path / subdir / split
                    if split_dir.exists():
                        for file in sorted(split_dir.iterdir()):
                            if file.is_file():
                                zf.write(file, f"{subdir}/{split}/{file.name}")

            # Add labels.txt
            labels_txt = dataset_path / "labels.txt"
            if labels_txt.exists():
                zf.write(labels_txt, "labels.txt")

            # Write a portable dataset.yaml (path: . instead of absolute)
            yaml_content = "# YOLO Dataset Configuration\npath: .\ntrain: images/train\nval: images/val\n\n# Classes\nnames:\n"
            for i, name in enumerate(class_names):
                yaml_content += f"  {i}: {name}\n"
            yaml_content += f"\n# Number of classes\nnc: {len(class_names)}\n"
            zf.writestr("dataset.yaml", yaml_content)

        logger.info(f"Exported dataset '{dataset_name}' as training zip: {tmp.name}")
        return tmp.name

    def export_dataset_snippets_zip(self, dataset_name: str) -> str:
        """
        Export dataset as cropped snippets with page name in filename, flat structure.

        Structure:
            page_001_entry_0.png, page_001_subentry_0.png, ...
            manifest.json

        Returns path to a temp zip file (caller must delete).
        """
        import zipfile
        import tempfile

        dataset_path = DATASETS_PATH / dataset_name
        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Read metadata for class names
        metadata_path = dataset_path / "metadata.json"
        class_names = {}
        if metadata_path.exists():
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)
                for c in metadata.get("classes", []):
                    class_names[c["id"]] = c["name"]

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix=f"{dataset_name}_snippets_")
        tmp.close()

        manifest = []
        ds_lower = dataset_name.lower()

        # Column-aware sort key matching save_ahw_entries_to_library ordering
        HEADER_CLASSES = {"guidewords", "pageNumber", "pagenumber"}

        def _is_header(class_name: str) -> bool:
            return class_name in HEADER_CLASSES or class_name.lower().replace("_", "").replace(" ", "") in HEADER_CLASSES

        def _ann_sort_key(rec):
            if _is_header(rec["class_name"]):
                return (0, rec["x_center"])
            col = 0 if rec["x_center"] < 0.5 else 1
            return (1, col, rec["y_center"])

        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            for split in ["train", "val"]:
                images_dir = dataset_path / "images" / split
                labels_dir = dataset_path / "labels" / split

                if not images_dir.exists():
                    continue

                for image_file in sorted(images_dir.iterdir()):
                    if not image_file.is_file():
                        continue
                    if image_file.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"):
                        continue

                    label_file = labels_dir / f"{image_file.stem}.txt"
                    if not label_file.exists():
                        continue

                    # Read annotations
                    annotations = []
                    with open(label_file, encoding="utf-8") as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) >= 5:
                                annotations.append({
                                    "class_id": int(parts[0]),
                                    "x_center": float(parts[1]),
                                    "y_center": float(parts[2]),
                                    "width": float(parts[3]),
                                    "height": float(parts[4]),
                                })

                    if not annotations:
                        continue

                    # Sort by y_center so index reflects top-to-bottom reading order
                    annotations.sort(key=lambda a: a["y_center"])

                    # Open image
                    try:
                        img = Image.open(image_file)
                        img_w, img_h = img.size
                    except Exception as e:
                        logger.warning(f"Snippets export: could not open {image_file}: {e}")
                        continue

                    page_stem = image_file.stem

                    # Build annotation records with pixel coords
                    page_records = []
                    class_counters = {}

                    for ann in annotations:
                        cid = ann["class_id"]
                        cname = class_names.get(cid, f"class_{cid}")

                        # YOLO normalized → pixel
                        cx = ann["x_center"] * img_w
                        cy = ann["y_center"] * img_h
                        bw = ann["width"] * img_w
                        bh = ann["height"] * img_h
                        x0 = max(0, int(cx - bw / 2))
                        y0 = max(0, int(cy - bh / 2))
                        x1 = min(img_w, int(cx + bw / 2))
                        y1 = min(img_h, int(cy + bh / 2))

                        if x1 <= x0 or y1 <= y0:
                            continue

                        crop = img.crop((x0, y0, x1, y1))

                        # Per-class index (matches download snippet naming)
                        idx = class_counters.get(cname, 0)
                        class_counters[cname] = idx + 1

                        page_records.append({
                            "class_name": cname,
                            "class_id": cid,
                            "class_index": idx,
                            "x_center": ann["x_center"],
                            "y_center": ann["y_center"],
                            "bbox_px": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
                            "crop": crop,
                            "width": ann["width"],
                            "height": ann["height"],
                            "width_px": x1 - x0,
                            "height_px": y1 - y0,
                        })

                    img.close()

                    # Compute merged_order: column-aware sort matching OCR numbering
                    sorted_for_merge = sorted(page_records, key=_ann_sort_key)
                    for merge_idx, rec in enumerate(sorted_for_merge):
                        rec["merged_order"] = merge_idx + 1

                    # Write crops and manifest entries in original y_center order
                    for rec in page_records:
                        cname = rec["class_name"]
                        idx = rec["class_index"]
                        snippet_name = f"{ds_lower}-{page_stem}-{idx:03d}-{cname}.png"

                        buf = BytesIO()
                        rec["crop"].save(buf, format="PNG")
                        zf.writestr(snippet_name, buf.getvalue())

                        column = "a" if rec["x_center"] < 0.5 else "b"

                        manifest.append({
                            "snippet": snippet_name,
                            "page": page_stem,
                            "column": column,
                            "merged_order": rec["merged_order"],
                            "split": split,
                            "class_name": cname,
                            "class_id": rec["class_id"],
                            "class_index": idx,
                            "bbox_px": rec["bbox_px"],
                            "x_center": round(rec["x_center"], 6),
                            "y_center": round(rec["y_center"], 6),
                            "width": round(rec["width"], 6),
                            "height": round(rec["height"], 6),
                            "width_px": rec["width_px"],
                            "height_px": rec["height_px"],
                        })

            # Write manifest
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

        logger.info(f"Exported dataset '{dataset_name}' as snippets zip: {len(manifest)} snippets")
        return tmp.name

    def save_snippets_to_library(self, dataset_name: str, project_id: str = None, project_name: str = None) -> Dict:
        """
        Save dataset snippets directly to the Pages library instead of a ZIP download.

        Flat structure with page name in filename (like AHw entries):
          project/
            page_001_entry_0.png, page_001_subentry_0.png, ...
            manifest.json

        All snippets are saved into one project with page name embedded in
        the filename. The manifest.json maps each snippet back to its class
        name, bounding box, and source page.

        Args:
            dataset_name: Name of the YOLO dataset
            project_id: Existing Pages project to save into (optional)
            project_name: Name for new project if project_id not given

        Returns:
            dict with project_id, name, snippet_count, manifest
        """
        from handlers.pages_handler import PagesHandler, _resolve_project_path

        dataset_path = DATASETS_PATH / dataset_name
        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Read metadata for class names
        metadata_path = dataset_path / "metadata.json"
        class_names = {}
        if metadata_path.exists():
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)
                for c in metadata.get("classes", []):
                    class_names[c["id"]] = c["name"]

        pages_handler = PagesHandler()

        # Create or reuse parent project
        if project_id:
            project_detail = pages_handler.get_project(project_id)
            if not project_detail:
                raise ValueError(f"Project '{project_id}' not found")
            result_project_id = project_id
            result_name = project_detail.name
        else:
            name = project_name or f"{dataset_name}_snippets"
            resp = pages_handler.create_project(name)
            result_project_id = resp.project_id
            result_name = resp.name

        manifest = []
        snippet_count = 0
        ds_lower = dataset_name.lower()

        HEADER_CLASSES = {"guidewords", "pageNumber", "pagenumber"}

        def _is_header(class_name: str) -> bool:
            return class_name in HEADER_CLASSES or class_name.lower().replace("_", "").replace(" ", "") in HEADER_CLASSES

        def _ann_sort_key(rec):
            if _is_header(rec["class_name"]):
                return (0, rec["x_center"])
            col = 0 if rec["x_center"] < 0.5 else 1
            return (1, col, rec["y_center"])

        for split in ["train", "val"]:
            images_dir = dataset_path / "images" / split
            labels_dir = dataset_path / "labels" / split

            if not images_dir.exists():
                continue

            for image_file in sorted(images_dir.iterdir()):
                if not image_file.is_file():
                    continue
                if image_file.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"):
                    continue

                label_file = labels_dir / f"{image_file.stem}.txt"
                if not label_file.exists():
                    continue

                # Read annotations
                annotations = []
                with open(label_file, encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            annotations.append({
                                "class_id": int(parts[0]),
                                "x_center": float(parts[1]),
                                "y_center": float(parts[2]),
                                "width": float(parts[3]),
                                "height": float(parts[4]),
                            })

                if not annotations:
                    continue

                # Sort by y_center (top-to-bottom reading order)
                annotations.sort(key=lambda a: a["y_center"])

                try:
                    img = Image.open(image_file)
                    img_w, img_h = img.size
                except Exception as e:
                    logger.warning(f"save_snippets_to_library: could not open {image_file}: {e}")
                    continue

                page_stem = image_file.stem

                class_counters = {}
                page_records = []

                for ann in annotations:
                    cid = ann["class_id"]
                    cname = class_names.get(cid, f"class_{cid}")

                    # YOLO normalized -> pixel
                    cx = ann["x_center"] * img_w
                    cy = ann["y_center"] * img_h
                    bw = ann["width"] * img_w
                    bh = ann["height"] * img_h
                    x0 = max(0, int(cx - bw / 2))
                    y0 = max(0, int(cy - bh / 2))
                    x1 = min(img_w, int(cx + bw / 2))
                    y1 = min(img_h, int(cy + bh / 2))

                    if x1 <= x0 or y1 <= y0:
                        continue

                    crop = img.crop((x0, y0, x1, y1))

                    idx = class_counters.get(cname, 0)
                    class_counters[cname] = idx + 1

                    page_records.append({
                        "class_name": cname,
                        "class_id": cid,
                        "class_index": idx,
                        "x_center": ann["x_center"],
                        "y_center": ann["y_center"],
                        "bbox_px": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
                        "crop": crop,
                        "width": ann["width"],
                        "height": ann["height"],
                        "width_px": x1 - x0,
                        "height_px": y1 - y0,
                    })

                img.close()

                # Compute merged_order: column-aware sort matching OCR numbering
                sorted_for_merge = sorted(page_records, key=_ann_sort_key)
                for merge_idx, rec in enumerate(sorted_for_merge):
                    rec["merged_order"] = merge_idx + 1

                # Write crops and manifest entries in original y_center order
                for rec in page_records:
                    cname = rec["class_name"]
                    idx = rec["class_index"]
                    snippet_name = f"{ds_lower}-{page_stem}-{idx:03d}-{cname}.png"

                    # Save crop to bytes and upload as page in the project
                    buf = BytesIO()
                    rec["crop"].save(buf, format="PNG")
                    crop_bytes = buf.getvalue()

                    pages_handler.upload_image(crop_bytes, snippet_name, project_id=result_project_id, preserve_name=True)
                    snippet_count += 1

                    column = "a" if rec["x_center"] < 0.5 else "b"

                    manifest.append({
                        "snippet": snippet_name,
                        "page": page_stem,
                        "column": column,
                        "merged_order": rec["merged_order"],
                        "split": split,
                        "class_name": cname,
                        "class_id": rec["class_id"],
                        "class_index": idx,
                        "bbox_px": rec["bbox_px"],
                        "x_center": round(rec["x_center"], 6),
                        "y_center": round(rec["y_center"], 6),
                        "width": round(rec["width"], 6),
                        "height": round(rec["height"], 6),
                        "width_px": rec["width_px"],
                        "height_px": rec["height_px"],
                    })

        # Save manifest.json into the parent project directory
        project_path = _resolve_project_path(result_project_id)
        manifest_path = project_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

        logger.info(f"Saved {snippet_count} snippets from dataset '{dataset_name}' to library project '{result_project_id}' (flat)")
        return {
            "project_id": result_project_id,
            "name": result_name,
            "snippet_count": snippet_count,
            "manifest": manifest,
        }

    def save_ahw_entries_to_library(self, dataset_name: str, project_id: str = None, project_name: str = None) -> Dict:
        """
        DEPRECATED: Use save_snippets_to_library instead.
        Save individual snippets and merge text content after OCR, not before.

        Save dataset snippets as merged AHw dictionary entries.

        All snippets saved flat into one project (no child folders).
        Processes pages in order; carries open mainEntry groups across page
        boundaries so that orphaned partEntries at the top of a page get
        merged with the mainEntry from the previous page.

        Naming: {dataset}_{pages}_{className}_{idx}.png
        Cross-page entries use page ranges: e.g. page_0001-page_0002
        """
        from handlers.pages_handler import PagesHandler, _resolve_project_path

        dataset_path = DATASETS_PATH / dataset_name
        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Read metadata for class names
        metadata_path = dataset_path / "metadata.json"
        class_names = {}
        if metadata_path.exists():
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)
                for c in metadata.get("classes", []):
                    class_names[c["id"]] = c["name"]

        entry_classes = {"mainEntry", "partEntry"}

        pages_handler = PagesHandler()

        # Create or reuse project
        if project_id:
            project_detail = pages_handler.get_project(project_id)
            if not project_detail:
                raise ValueError(f"Project '{project_id}' not found")
            result_project_id = project_id
            result_name = project_detail.name
        else:
            name = project_name or f"{dataset_name}_ahw"
            resp = pages_handler.create_project(name)
            result_project_id = resp.project_id
            result_name = resp.name

        ds_lower = dataset_name.lower()

        # ---- Pass 1: collect per-page data across all splits ----
        page_data = []
        for split in ["train", "val"]:
            images_dir = dataset_path / "images" / split
            labels_dir = dataset_path / "labels" / split
            if not images_dir.exists():
                continue

            for image_file in sorted(images_dir.iterdir()):
                if not image_file.is_file():
                    continue
                if image_file.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"):
                    continue
                label_file = labels_dir / f"{image_file.stem}.txt"
                if not label_file.exists():
                    continue

                annotations = []
                with open(label_file, encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            annotations.append({
                                "class_id": int(parts[0]),
                                "x_center": float(parts[1]),
                                "y_center": float(parts[2]),
                                "width": float(parts[3]),
                                "height": float(parts[4]),
                            })
                if annotations:
                    annotations.sort(key=lambda a: a["y_center"])
                    page_data.append({
                        "page_stem": image_file.stem,
                        "split": split,
                        "image_path": image_file,
                        "annotations": annotations,
                    })

        # Sort all pages by page stem so train/val are interleaved by page number
        page_data.sort(key=lambda pd: pd["page_stem"])

        # ---- Pass 2: build flat ordered annotation list across all pages ----
        # .copy() is essential – PIL crops are lazy references; after
        # img.close() the pixel data can become invalid.
        #
        # Per-page sort order (two-column dictionary layout):
        #   Header region: guidewords + pageNumbers — sorted by x_center (left→right)
        #   Body region: left column (x<0.5) top→bottom, then right column top→bottom
        #
        # Classes: guidewords, pageNumber = header
        #          mainEntry, partEntry, refEntry, etc. = body
        HEADER_CLASSES = {"guidewords", "pageNumber", "pagenumber"}

        def _is_header(class_name: str) -> bool:
            return class_name in HEADER_CLASSES or class_name.lower().replace("_", "").replace(" ", "") in HEADER_CLASSES

        def _ann_sort_key(rec):
            if _is_header(rec["class_name"]):
                # Header: sort left-to-right by x position
                # → guideword(left) → pageNumber(center) → guideword(right)
                return (0, rec["x_center"])
            # Body: left column first, then right column, each top-to-bottom
            column = 0 if rec["x_center"] < 0.5 else 1
            return (1, column, rec["y_center"])

        all_anns = []

        for pd in page_data:
            try:
                img = Image.open(pd["image_path"])
                img_w, img_h = img.size
            except Exception as e:
                logger.warning(f"save_ahw_entries: could not open {pd['image_path']}: {e}")
                continue

            page_stem = pd["page_stem"]
            split = pd["split"]
            page_anns = []

            # Sort annotations by y_center first (matching download/snippet order)
            # to assign per-class snippet_index before column-aware resorting.
            sorted_by_y = sorted(pd["annotations"], key=lambda a: a["y_center"])
            class_counters = {}

            for ann in sorted_by_y:
                cname = class_names.get(ann["class_id"], f"class_{ann['class_id']}")
                cx, cy = ann["x_center"] * img_w, ann["y_center"] * img_h
                bw, bh = ann["width"] * img_w, ann["height"] * img_h
                x0 = max(0, int(cx - bw / 2))
                y0 = max(0, int(cy - bh / 2))
                x1 = min(img_w, int(cx + bw / 2))
                y1 = min(img_h, int(cy + bh / 2))
                if x1 <= x0 or y1 <= y0:
                    continue
                crop = img.crop((x0, y0, x1, y1)).copy()
                column = "a" if ann["x_center"] < 0.5 else "b"

                # snippet_index matches the per-class counter used by
                # export_dataset_snippets_zip, so entries can be cross-referenced.
                snippet_idx = class_counters.get(cname, 0)
                class_counters[cname] = snippet_idx + 1

                page_anns.append({
                    "class_name": cname,
                    "class_id": ann["class_id"],
                    "snippet_index": snippet_idx,
                    "bbox_px": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
                    "x_center": ann["x_center"],
                    "y_center": ann["y_center"],
                    "column": column,
                    "crop": crop,
                    "page_stem": page_stem,
                    "split": split,
                })

            img.close()

            # Sort: headers first, then left column top-to-bottom, then right column
            page_anns.sort(key=_ann_sort_key)
            all_anns.extend(page_anns)

        # ---- Pass 3: assign per-page order numbers ----
        # Extract page number from page_stem (e.g. "page_0001" → "0001")
        def _extract_page_num(page_stem: str) -> str:
            m = re.search(r'(\d+)$', page_stem)
            return m.group(1) if m else page_stem

        current_page = None
        page_order = 0
        for ann in all_anns:
            if ann["page_stem"] != current_page:
                current_page = ann["page_stem"]
                page_order = 0
            page_order += 1
            ann["order"] = page_order
            ann["page_num"] = _extract_page_num(ann["page_stem"])

        # ---- Pass 4a: same-page forward-looking merge → save_items ----
        # Collect items without saving to disk yet so we can do cross-page
        # merging in Pass 4b.
        #
        # Each save_item has: type, crops (list of PIL), anns (list of recs),
        # page_num, page_stem, entry_type
        save_items = []
        i = 0

        while i < len(all_anns):
            rec = all_anns[i]
            group = None

            if rec["class_name"] == "mainEntry":
                group = [rec]
                j = i + 1
                while (j < len(all_anns)
                       and all_anns[j]["class_name"] == "partEntry"
                       and all_anns[j]["page_stem"] == rec["page_stem"]):
                    group.append(all_anns[j])
                    j += 1

            elif rec["class_name"] == "partEntry":
                group = [rec]
                j = i + 1
                while (j < len(all_anns)
                       and all_anns[j]["class_name"] == "partEntry"
                       and all_anns[j]["page_stem"] == rec["page_stem"]):
                    group.append(all_anns[j])
                    j += 1

            if group is not None:
                save_items.append({
                    "kind": "group",
                    "entry_type": group[0]["class_name"],
                    "anns": group,
                    "crops": [a["crop"] for a in group],
                    "pages": [group[0]["page_num"]],
                    "page_stems": [group[0]["page_stem"]],
                })
                i = j
            else:
                save_items.append({
                    "kind": "single",
                    "entry_type": rec["class_name"],
                    "anns": [rec],
                    "crops": [rec["crop"]],
                    "pages": [rec["page_num"]],
                    "page_stems": [rec["page_stem"]],
                })
                i += 1

        # ---- Pass 4b: cross-page merge ----
        # Separate headers from body so headers don't block cross-page merges.
        # Merge body entries across pages, then recombine.
        header_items = []
        body_items = []
        for item in save_items:
            if _is_header(item["entry_type"]):
                header_items.append(item)
            else:
                body_items.append(item)

        # Merge body items across pages:
        # - orphan partEntry after mainEntry → attach to mainEntry
        merged_body = []
        for item in body_items:
            if (item["entry_type"] == "partEntry"
                    and merged_body
                    and merged_body[-1]["entry_type"] == "mainEntry"):
                prev = merged_body[-1]
                prev["anns"].extend(item["anns"])
                prev["crops"].extend(item["crops"])
                if item["pages"][0] not in prev["pages"]:
                    prev["pages"].append(item["pages"][0])
                if item["page_stems"][0] not in prev["page_stems"]:
                    prev["page_stems"].append(item["page_stems"][0])
                logger.info(
                    f"Cross-page merge: partEntry from page {item['pages'][0]} "
                    f"→ mainEntry from page {prev['pages'][0]}"
                )
            else:
                merged_body.append(item)

        # Recombine: headers first, then body entries
        merged_items = header_items + merged_body

        # ---- Pass 5: save to disk ----
        # Naming:
        #   single page:  {ds_lower}-{page}-{order}-{type}.png
        #   same-page range: {ds_lower}-{page}-{first}-{last}-{type}.png
        #   cross-page:   {ds_lower}-{page1}-{order}-p{page2}-{type}.png
        manifest = []
        entry_count = 0

        for item in merged_items:
            anns = item["anns"]
            crops = item["crops"]
            entry_type = item["entry_type"]
            first_page = item["pages"][0]
            first_order = anns[0]["order"]
            last_order = anns[-1]["order"]

            # Build merged image
            if len(crops) == 1:
                merged_img = crops[0]
            else:
                total_w = max(c.width for c in crops)
                total_h = sum(c.height for c in crops)
                merged_img = Image.new("RGB", (total_w, total_h), (255, 255, 255))
                y_off = 0
                for c in crops:
                    merged_img.paste(c, (0, y_off))
                    y_off += c.height

            # Build filename
            if len(item["pages"]) > 1:
                # Cross-page: {ds_lower}-{page1}-{order}-p{page2}-{type}.png
                last_page = item["pages"][-1]
                fname = f"{ds_lower}-{first_page}-{first_order:03d}-p{last_page}-{entry_type}.png"
            elif first_order == last_order:
                fname = f"{ds_lower}-{first_page}-{first_order:03d}-{entry_type}.png"
            else:
                fname = f"{ds_lower}-{first_page}-{first_order:03d}-{last_order:03d}-{entry_type}.png"

            buf = BytesIO()
            merged_img.save(buf, format="PNG")
            pages_handler.upload_image(buf.getvalue(), fname, project_id=result_project_id, preserve_name=True)
            entry_count += 1

            # Column: collect unique columns preserving order (e.g. "a", "ab", "b")
            seen_cols = []
            for a in anns:
                c = a.get("column", "a")
                if c not in seen_cols:
                    seen_cols.append(c)
            entry_column = "".join(seen_cols)

            manifest.append({
                "entry": fname,
                "pages": item["pages"],
                "page_stems": item["page_stems"],
                "column": entry_column,
                "order_start": first_order,
                "order_end": last_order,
                "split": anns[0]["split"],
                "type": entry_type,
                "merged_count": len(anns),
                "merged_from": [
                    {"class_name": a["class_name"], "order": a["order"],
                     "snippet_index": a.get("snippet_index", 0),
                     "page": a["page_num"], "column": a.get("column", "a"),
                     "bbox_px": a["bbox_px"]}
                    for a in anns
                ],
                "width_px": merged_img.width,
                "height_px": merged_img.height,
            })

        class_breakdown = {}
        for m_entry in manifest:
            cn = m_entry["type"]
            class_breakdown[cn] = class_breakdown.get(cn, 0) + 1
        cross_page = sum(1 for m_entry in manifest if len(m_entry.get("pages", [])) > 1)
        merged_entries = sum(1 for m_entry in manifest if m_entry.get("merged_count", 1) > 1)
        logger.info(
            f"save_ahw_entries: {entry_count} files ({merged_entries} merged, "
            f"{cross_page} cross-page), classes: {class_breakdown}"
        )

        # Save manifest
        project_path = _resolve_project_path(result_project_id)
        manifest_path = project_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

        logger.info(f"Saved {entry_count} AHw snippets from dataset '{dataset_name}' to project '{result_project_id}'")
        return {
            "project_id": result_project_id,
            "name": result_name,
            "entry_count": entry_count,
            "manifest": manifest,
        }

    # ============== PDF to Images ==============

    def convert_pdf_to_images(
        self,
        pdf_base64: str,
        output_name: str,
        dpi: int = 200,
        page_range: Optional[Tuple[int, int]] = None
    ) -> Dict:
        """
        Convert a PDF to PNG images and save them to disk.

        Args:
            pdf_base64: Base64-encoded PDF bytes
            output_name: Name for the output directory
            dpi: Resolution for rendering (default 200)
            page_range: Optional (start, end) 1-indexed page range

        Returns:
            Dict with success, output_name, page_count, output_path
        """
        import pypdfium2 as pdfium

        # Sanitize output name
        output_name = output_name.strip().replace(" ", "_")
        output_dir = PDF_IMAGES_PATH / output_name
        if output_dir.exists():
            raise ValueError(f"Output '{output_name}' already exists. Delete it first or choose another name.")

        output_dir.mkdir(parents=True)

        # Decode PDF
        pdf_bytes = base64.b64decode(pdf_base64)
        pdf = pdfium.PdfDocument(pdf_bytes)
        total_pages = len(pdf)

        # Determine page range
        start = 1
        end = total_pages
        if page_range:
            start = max(1, page_range[0])
            end = min(total_pages, page_range[1])

        scale = dpi / 72  # PDF default is 72 DPI
        saved_pages = []

        for page_num in range(start, end + 1):
            pdf_page = pdf[page_num - 1]
            bitmap = pdf_page.render(scale=scale)
            pil_image = bitmap.to_pil()

            filename = f"page_{page_num:04d}.png"
            filepath = output_dir / filename
            pil_image.save(filepath, format="PNG", optimize=False)
            saved_pages.append(filename)

            logger.info(f"PDF->PNG: {output_name}/{filename} ({pil_image.width}x{pil_image.height})")

        logger.info(f"PDF conversion complete: {output_name}, {len(saved_pages)} pages at {dpi} DPI")

        return {
            "success": True,
            "output_name": output_name,
            "page_count": len(saved_pages),
            "total_pdf_pages": total_pages,
            "dpi": dpi,
            "pages": saved_pages,
            "output_path": str(output_dir),
        }

    def list_pdf_image_sets(self) -> List[Dict]:
        """List all converted PDF image sets."""
        sets = []
        if not PDF_IMAGES_PATH.exists():
            return sets

        for d in sorted(PDF_IMAGES_PATH.iterdir()):
            if d.is_dir():
                images = list(d.glob("*.png"))
                sets.append({
                    "name": d.name,
                    "image_count": len(images),
                    "created_at": datetime.fromtimestamp(d.stat().st_ctime).isoformat(),
                })

        return sets

    def get_pdf_image_set(self, set_name: str) -> Dict:
        """Get details of a PDF image set including list of images."""
        set_dir = PDF_IMAGES_PATH / set_name
        if not set_dir.exists():
            raise ValueError(f"PDF image set '{set_name}' not found")

        images = sorted(set_dir.glob("*.png"))
        return {
            "name": set_name,
            "image_count": len(images),
            "images": [img.name for img in images],
            "path": str(set_dir),
        }

    def get_pdf_image(self, set_name: str, image_name: str) -> bytes:
        """Get a specific image from a PDF image set as bytes."""
        img_path = PDF_IMAGES_PATH / set_name / image_name
        if not img_path.exists():
            raise ValueError(f"Image '{image_name}' not found in set '{set_name}'")
        return img_path.read_bytes()

    def delete_pdf_image_set(self, set_name: str) -> Dict:
        """Delete a PDF image set."""
        set_dir = PDF_IMAGES_PATH / set_name
        if not set_dir.exists():
            raise ValueError(f"PDF image set '{set_name}' not found")

        shutil.rmtree(set_dir)
        return {"success": True, "message": f"Deleted '{set_name}'"}


# Global instance
yolo_training_client = YoloTrainingClient()
