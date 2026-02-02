"""
YOLO Training Client - Handles YOLOv8 model training and inference.
"""

import os
import logging
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

# Data paths
DATA_ROOT = Path(os.environ.get("YOLO_DATA_PATH", "/data/yolo"))
DATASETS_PATH = DATA_ROOT / "datasets"
MODELS_PATH = DATA_ROOT / "models"
BASE_MODELS_PATH = DATA_ROOT / "base_models"
TRAINING_RUNS_PATH = DATA_ROOT / "runs"

# Ensure directories exist
for path in [DATASETS_PATH, MODELS_PATH, BASE_MODELS_PATH, TRAINING_RUNS_PATH]:
    path.mkdir(parents=True, exist_ok=True)

# Default classes for dictionary layout
DEFAULT_CLASSES = ["entry", "subentry", "guidewords", "page_number", "root_index"]

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

        with open(dataset_path / "dataset.yaml", "w") as f:
            f.write(yaml_content)

        # Create labels.txt for annotation tools
        with open(dataset_path / "labels.txt", "w") as f:
            f.write("\n".join(classes))

        # Create metadata.json
        metadata = {
            "name": name,
            "description": description or "",
            "classes": [{"id": i, "name": c} for i, c in enumerate(classes)],
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        with open(dataset_path / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Created dataset '{name}' with {len(classes)} classes")

        return {
            "dataset_id": name,
            "name": name,
            "classes": metadata["classes"],
            "path": str(dataset_path),
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
        with open(label_path, "w") as f:
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
        issues = []
        total_images = len(train_images) + len(val_images)

        if len(train_images) < MIN_TRAINING_IMAGES:
            issues.append(f"Need at least {MIN_TRAINING_IMAGES} training images, have {len(train_images)}")

        if len(val_images) < MIN_VAL_IMAGES:
            issues.append(f"Need at least {MIN_VAL_IMAGES} validation images, have {len(val_images)}")

        for class_name, count in class_distribution.items():
            if count < MIN_INSTANCES_PER_CLASS:
                issues.append(f"Class '{class_name}' needs at least {MIN_INSTANCES_PER_CLASS} instances, has {count}")

        return {
            "dataset_id": dataset_name,
            "name": metadata["name"],
            "classes": metadata["classes"],
            "total_images": total_images,
            "train_images": len(train_images),
            "val_images": len(val_images),
            "total_annotations": total_annotations,
            "class_distribution": class_distribution,
            "ready_for_training": len(issues) == 0,
            "issues": issues,
        }

    def list_datasets(self) -> List[Dict]:
        """List all available datasets."""
        datasets = []

        for dataset_dir in DATASETS_PATH.iterdir():
            if dataset_dir.is_dir() and (dataset_dir / "metadata.json").exists():
                with open(dataset_dir / "metadata.json") as f:
                    metadata = json.load(f)

                # Count images
                train_count = len(list((dataset_dir / "images" / "train").glob("*")))
                val_count = len(list((dataset_dir / "images" / "val").glob("*")))

                datasets.append({
                    "dataset_id": dataset_dir.name,
                    "name": metadata.get("name", dataset_dir.name),
                    "class_count": len(metadata.get("classes", [])),
                    "image_count": train_count + val_count,
                    "created_at": metadata.get("created_at"),
                    "updated_at": metadata.get("updated_at"),
                })

        return sorted(datasets, key=lambda x: x.get("updated_at", ""), reverse=True)

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
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

    def list_dataset_images(self, dataset_name: str) -> List[Dict]:
        """List all images in a dataset with their annotation counts."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

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
                })

        return sorted(images, key=lambda x: (x["split"], x["filename"]))

    def get_dataset_image(self, dataset_name: str, image_id: str, split: str = None) -> Dict:
        """Get a specific image with its annotations from the dataset."""
        dataset_path = DATASETS_PATH / dataset_name

        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        # Load dataset metadata for class names
        metadata_path = dataset_path / "metadata.json"
        class_names = {}
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
                for cls in metadata.get("classes", []):
                    class_names[cls["id"]] = cls["name"]

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
            }

        raise ValueError(f"Image '{image_id}' not found in dataset '{dataset_name}'")

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
            with open(label_file, "w") as f:
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
            return BASE_MODELS_PATH / model_name

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

        shutil.rmtree(model_path)
        logger.info(f"Deleted model '{model_name}'")

        # Clear from cache
        if model_name in self._model_cache:
            del self._model_cache[model_name]

        return True

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

        # Get dataset stats to validate
        stats = self.get_dataset_stats(dataset_name)
        if not stats["ready_for_training"]:
            raise ValueError(f"Dataset not ready for training: {stats['issues']}")

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

        results = model.train(
            data=str(dataset_path / "dataset.yaml"),
            epochs=config["epochs"],
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

        # Save metadata
        metadata = {
            "name": output_name,
            "base_model": base_model,
            "dataset_name": dataset_name,
            "classes": stats["classes"],
            "metrics": metrics,
            "created_at": datetime.utcnow().isoformat(),
            "training_epochs": config["epochs"],
            "training_config": config,
            "training_time_seconds": training_time,
        }
        with open(output_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Training complete: {output_name}, mAP50={metrics.get('mAP50', 0):.3f}")

        return {
            "success": True,
            "model_id": output_name,
            "metrics": metrics,
            "training_time_seconds": training_time,
            "model_path": str(output_dir / "best.pt"),
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
            # Use first available trained model, or base model
            models = self.list_models()
            if models["models"]:
                model_name = models["models"][0]["model_id"]
            else:
                raise ValueError("No trained models available. Train a model first.")

        # Load model (with caching)
        if model_name not in self._model_cache:
            model_path = self.get_model_path(model_name)
            self._model_cache[model_name] = YOLO(str(model_path))

        model = self._model_cache[model_name]

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

        return {
            "success": True,
            "detections": detections,
            "model_used": model_name,
            "processing_time_ms": processing_time,
            "image_size": {"width": img_width, "height": img_height},
        }


# Global instance
yolo_training_client = YoloTrainingClient()
