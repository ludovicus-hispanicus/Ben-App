"""
Kraken OCR Training Service

Handles training data export and model training for Kraken OCR.
Supports both Kraken 5.x and 6.x versions.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional, Callable, Tuple
from PIL import Image
import base64
import io


def get_kraken_version() -> Tuple[int, int, int]:
    """
    Get the installed Kraken version.
    Returns tuple (major, minor, patch) or (0, 0, 0) if unable to detect.
    """
    try:
        result = subprocess.run(
            ["kraken", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        # Parse version from output like "kraken 5.2.9" or "6.0.3"
        output = result.stdout.strip() or result.stderr.strip()
        import re
        match = re.search(r'(\d+)\.(\d+)\.(\d+)', output)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except Exception as e:
        logging.warning(f"Could not detect Kraken version: {e}")
    return (0, 0, 0)


KRAKEN_VERSION = get_kraken_version()
logging.info(f"Detected Kraken version: {KRAKEN_VERSION[0]}.{KRAKEN_VERSION[1]}.{KRAKEN_VERSION[2]}")


class TrainingStatus(Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    TRAINING = "training"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TrainingProgress:
    status: TrainingStatus
    epoch: int
    total_epochs: int
    accuracy: float
    val_accuracy: float
    loss: float
    eta_seconds: int
    message: str
    model_name: str = None
    error: str = None
    started_at: str = None
    completed_at: str = None

    def to_dict(self):
        return {
            "status": self.status.value,
            "current_epoch": self.epoch,  # Frontend expects current_epoch
            "total_epochs": self.total_epochs,
            "accuracy": self.accuracy,
            "val_accuracy": self.val_accuracy,
            "loss": self.loss,
            "eta_seconds": self.eta_seconds,
            "message": self.message,
            "model_name": self.model_name,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }


@dataclass
class TrainingDataItem:
    """Represents a single training item (line image + ground truth)"""
    image_path: str
    ground_truth: str
    text_id: int
    line_index: int


class KrakenTrainingService:
    """Service for training Kraken OCR models."""

    TRAINING_DATA_DIR = "/data/server-storage/kraken-training"
    MODELS_DIR = "/app/cured_models"
    # Store history in parent dir so it doesn't get deleted when clearing training data
    TRAINING_HISTORY_FILE = "/data/server-storage/training_history.json"
    MIN_LINES = 1000

    def __init__(self):
        self.progress = TrainingProgress(
            status=TrainingStatus.IDLE,
            epoch=0,
            total_epochs=50,
            accuracy=0.0,
            val_accuracy=0.0,
            loss=0.0,
            eta_seconds=0,
            message=""
        )
        self.process: Optional[subprocess.Popen] = None
        self._ensure_directories()
        self._training_history = self._load_training_history()

    def _load_training_history(self) -> dict:
        """Load training history from file."""
        try:
            if os.path.exists(self.TRAINING_HISTORY_FILE):
                with open(self.TRAINING_HISTORY_FILE, "r") as f:
                    return json.load(f)
        except Exception as e:
            logging.warning(f"Could not load training history: {e}")
        return {
            "last_training_timestamp": None,
            "previous_lines": 0,
            "trained_text_ids": []
        }

    def _save_training_history(self, trained_lines: int, trained_text_ids: List[int]):
        """Save training history after successful training."""
        self._training_history = {
            "last_training_timestamp": datetime.now().isoformat(),
            "previous_lines": trained_lines,
            "trained_text_ids": trained_text_ids
        }
        try:
            with open(self.TRAINING_HISTORY_FILE, "w") as f:
                json.dump(self._training_history, f, indent=2)
        except Exception as e:
            logging.error(f"Could not save training history: {e}")

    def get_training_stats(self, texts_handler) -> dict:
        """Get training statistics with previous/new breakdown."""
        curated_stats = texts_handler.get_curated_training_stats()
        total_lines = curated_stats.get("total_lines", 0)
        total_texts = curated_stats.get("curated_texts", 0)

        previous_lines = self._training_history.get("previous_lines", 0)
        new_lines = max(0, total_lines - previous_lines)

        return {
            "previous_lines": previous_lines,
            "new_lines": new_lines,
            "total_lines": total_lines,
            "curated_texts": total_texts,
            "last_training": self._training_history.get("last_training_timestamp")
        }

    def _ensure_directories(self):
        """Ensure training directories exist."""
        Path(self.TRAINING_DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.MODELS_DIR).mkdir(parents=True, exist_ok=True)

    def _build_training_command(
        self,
        output_path: str,
        epochs: int,
        base_model: Optional[str],
        training_pattern: str
    ) -> List[str]:
        """
        Build ketos train command with version-aware flags.
        Supports both Kraken 5.x and 6.x.
        """
        cmd = ["ketos", "train"]

        # Output path (same for both versions)
        cmd.extend(["-o", output_path])

        # Number of epochs (same for both versions)
        cmd.extend(["-N", str(epochs)])

        # Early stopping - syntax may vary
        if KRAKEN_VERSION[0] >= 6:
            # Kraken 6.x syntax
            cmd.extend(["-q", "early", "--min-delta", "0.001", "--lag", "5"])
        else:
            # Kraken 5.x syntax
            cmd.extend(["-q", "early", "--lag", "5"])

        # Learning rate
        cmd.extend(["-r", "0.0001"])

        # Device selection for GPU (Kraken 6.x has better GPU support)
        if KRAKEN_VERSION[0] >= 6:
            # Check if CUDA is available
            try:
                import torch
                if torch.cuda.is_available():
                    cmd.extend(["--device", "cuda:0"])
                    logging.info("Using CUDA for training (Kraken 6.x)")
            except ImportError:
                pass

        # Add base model for fine-tuning if provided
        if base_model and os.path.exists(base_model):
            cmd.extend(["-i", base_model])
        elif os.path.exists(f"{self.MODELS_DIR}/model.mlmodel"):
            # Use default model as base
            cmd.extend(["-i", f"{self.MODELS_DIR}/model.mlmodel"])

        # Add training data pattern
        cmd.append(training_pattern)

        logging.info(f"Built training command for Kraken {KRAKEN_VERSION[0]}.{KRAKEN_VERSION[1]}.{KRAKEN_VERSION[2]}")

        return cmd

    def export_training_data(self, texts_handler) -> dict:
        """
        Export curated texts as training data (line images + ground truth).
        Returns statistics about the exported data.
        """
        logging.info("Exporting training data from curated texts...")

        # Clear old training data
        training_dir = Path(self.TRAINING_DATA_DIR)
        if training_dir.exists():
            for f in training_dir.glob("*"):
                if f.is_file():
                    f.unlink()

        exported_lines = 0
        exported_texts = 0
        exported_text_ids = []

        # Get all curated texts with their data
        curated_data = texts_handler.get_curated_training_data()

        for text_data in curated_data:
            text_id = text_data["text_id"]
            image_path = text_data["image_path"]
            lines = text_data["lines"]
            boxes = text_data["boxes"]

            if not os.path.exists(image_path):
                logging.warning(f"Image not found: {image_path}")
                continue

            try:
                # Open the full image
                full_image = Image.open(image_path)

                # Extract each line as a separate image
                for i, (line_text, box) in enumerate(zip(lines, boxes)):
                    if not line_text.strip():
                        continue

                    # Crop the line from the image
                    x = box.get("x", 0)
                    y = box.get("y", 0)
                    width = box.get("width", 0)
                    height = box.get("height", 0)

                    if width <= 0 or height <= 0:
                        continue

                    line_image = full_image.crop((x, y, x + width, y + height))

                    # Save line image as PNG
                    line_filename = f"text{text_id}_line{i:03d}.png"
                    line_image_path = training_dir / line_filename
                    line_image.save(str(line_image_path), "PNG")

                    # Save ground truth as .gt.txt file (Kraken format)
                    gt_filename = f"text{text_id}_line{i:03d}.gt.txt"
                    gt_path = training_dir / gt_filename
                    with open(gt_path, "w", encoding="utf-8") as f:
                        f.write(line_text.strip())

                    exported_lines += 1

                exported_texts += 1
                exported_text_ids.append(text_id)

            except Exception as e:
                logging.error(f"Error processing text {text_id}: {e}")
                continue

        logging.info(f"Exported {exported_lines} lines from {exported_texts} texts")

        return {
            "exported_lines": exported_lines,
            "exported_texts": exported_texts,
            "exported_text_ids": exported_text_ids,
            "training_dir": str(training_dir)
        }

    async def start_training(
        self,
        texts_handler,
        epochs: int = 50,
        model_name: Optional[str] = None,
        base_model: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """
        Start Kraken model training.

        Args:
            texts_handler: Handler to get training data
            epochs: Number of training epochs
            model_name: Optional name for the output model
            base_model: Optional path to base model for fine-tuning
            progress_callback: Optional callback for progress updates

        Returns:
            dict with training results
        """
        try:
            logging.info(f"=== Starting training: epochs={epochs}, model_name={model_name} ===")

            self.progress.status = TrainingStatus.PREPARING
            self.progress.message = "Exporting training data..."
            self.progress.total_epochs = epochs
            self.progress.model_name = model_name
            self.progress.started_at = datetime.now().isoformat()
            self.progress.error = None
            self.progress.completed_at = None

            if progress_callback:
                await progress_callback(self.progress)

            # Export training data
            logging.info("Exporting training data...")
            export_result = self.export_training_data(texts_handler)
            logging.info(f"Export result: {export_result}")

            if export_result["exported_lines"] < self.MIN_LINES:
                raise ValueError(
                    f"Not enough training data. Need at least {self.MIN_LINES} lines, "
                    f"got {export_result['exported_lines']}"
                )

            # Generate model name if not provided
            if not model_name:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                model_name = f"custom_model_{timestamp}"

            output_path = Path(self.MODELS_DIR) / f"{model_name}.mlmodel"

            # Build ketos train command - version aware
            # For PNG + .gt.txt pairs, use default "path" format (no -f flag)
            cmd = self._build_training_command(
                output_path=str(output_path),
                epochs=epochs,
                base_model=base_model,
                training_pattern=f"{self.TRAINING_DATA_DIR}/*.png"
            )

            logging.info(f"Starting training with command: {' '.join(cmd)}")

            self.progress.status = TrainingStatus.TRAINING
            self.progress.message = "Training in progress..."

            if progress_callback:
                await progress_callback(self.progress)

            # Run training
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Monitor progress
            for line in iter(self.process.stdout.readline, ''):
                self._parse_progress(line.strip())
                logging.info(f"[ketos] {line.strip()}")

                if progress_callback:
                    await progress_callback(self.progress)

            self.process.wait()

            if self.process.returncode == 0:
                self.progress.status = TrainingStatus.COMPLETED
                self.progress.message = f"Training completed! Model saved to {output_path}"
                self.progress.completed_at = datetime.now().isoformat()
                self.progress.model_name = model_name
                logging.info(f"=== Training completed successfully: {model_name} ===")

                # Save training history with the lines used
                self._save_training_history(
                    trained_lines=export_result["exported_lines"],
                    trained_text_ids=export_result["exported_text_ids"]
                )

                # Register the new model
                self._register_model(str(output_path), model_name, epochs)

                return {
                    "success": True,
                    "model_path": str(output_path),
                    "model_name": model_name,
                    "final_accuracy": self.progress.accuracy
                }
            else:
                self.progress.status = TrainingStatus.FAILED
                self.progress.message = "Training failed"
                self.progress.error = "Training process exited with non-zero code"
                self.progress.completed_at = datetime.now().isoformat()
                logging.error("=== Training failed: non-zero exit code ===")
                return {
                    "success": False,
                    "error": "Training process exited with non-zero code"
                }

        except Exception as e:
            logging.error(f"=== Training error: {e} ===")
            self.progress.status = TrainingStatus.FAILED
            self.progress.message = str(e)
            self.progress.error = str(e)
            self.progress.completed_at = datetime.now().isoformat()
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            self.process = None

    def _parse_progress(self, line: str):
        """Parse Kraken/ketos training output for progress info."""
        import re

        # Example: "stage 1/50   [==========] loss: 0.234 accuracy: 0.891"
        # Or: "Epoch 10: loss=0.234, accuracy=0.891"

        # Try to parse epoch
        epoch_match = re.search(r"(?:stage|epoch)\s*(\d+)(?:/(\d+))?", line, re.I)
        if epoch_match:
            self.progress.epoch = int(epoch_match.group(1))
            if epoch_match.group(2):
                self.progress.total_epochs = int(epoch_match.group(2))

        # Try to parse loss
        loss_match = re.search(r"loss[:\s=]+([0-9.]+)", line, re.I)
        if loss_match:
            self.progress.loss = float(loss_match.group(1))

        # Try to parse accuracy
        acc_match = re.search(r"accuracy[:\s=]+([0-9.]+)", line, re.I)
        if acc_match:
            self.progress.accuracy = float(acc_match.group(1))

        # Try to parse val accuracy
        val_acc_match = re.search(r"val[_\s]*acc[uracy]*[:\s=]+([0-9.]+)", line, re.I)
        if val_acc_match:
            self.progress.val_accuracy = float(val_acc_match.group(1))

    def _register_model(self, model_path: str, model_name: str, epochs: int):
        """Register a trained model in the registry."""
        registry_path = Path(self.MODELS_DIR) / "registry.json"

        # Load existing registry
        registry = []
        if registry_path.exists():
            with open(registry_path, "r") as f:
                registry = json.load(f)

        # Add new model
        registry.append({
            "name": model_name,
            "path": model_path,
            "created": datetime.now().isoformat(),
            "epochs": epochs,
            "accuracy": self.progress.accuracy
        })

        # Save registry
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)

    def cancel_training(self):
        """Cancel ongoing training."""
        logging.info("=== Cancelling training ===")
        if self.process:
            self.process.terminate()
        self.progress.status = TrainingStatus.CANCELLED
        self.progress.message = "Training cancelled"
        self.progress.completed_at = datetime.now().isoformat()

    def get_models(self) -> List[dict]:
        """List available trained models."""
        models = []
        models_dir = Path(self.MODELS_DIR)

        for model_path in models_dir.glob("*.mlmodel"):
            stat = model_path.stat()
            models.append({
                "name": model_path.stem,
                "path": str(model_path),
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })

        return sorted(models, key=lambda x: x["created"], reverse=True)

    def get_active_model_info(self) -> dict:
        """Get information about the currently active model."""
        # The active model is always at ./cured_models/model.mlmodel (relative to server working dir)
        active_model_path = Path("/code/src/cured_models/model.mlmodel")

        if not active_model_path.exists():
            return {
                "name": "No Model",
                "is_pretrained": False,
                "size_mb": 0,
                "last_modified": None
            }

        stat = active_model_path.stat()
        size_mb = round(stat.st_size / 1024 / 1024, 2)
        last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Pre-trained model is approximately 17MB
        # Custom trained models are typically smaller (around 16MB)
        # Also check if it was modified by our training (compare with registry)
        is_pretrained = True
        model_name = "Pre-trained (Default)"

        # Check registry to see if active model matches any trained model
        registry_path = Path(self.MODELS_DIR) / "registry.json"
        if registry_path.exists():
            try:
                with open(registry_path, "r") as f:
                    registry = json.load(f)
                    for model in registry:
                        # Check if any registered model was activated (same size/time)
                        model_path = Path(model.get("path", ""))
                        if model_path.exists():
                            model_stat = model_path.stat()
                            # If the active model matches a trained model in size, it's likely that one
                            if abs(model_stat.st_size - stat.st_size) < 1000:  # Within 1KB
                                is_pretrained = False
                                model_name = model.get("name", "Custom Model")
                                break
            except Exception as e:
                logging.warning(f"Could not read model registry: {e}")

        return {
            "name": model_name,
            "is_pretrained": is_pretrained,
            "size_mb": size_mb,
            "last_modified": last_modified
        }

    def activate_model(self, model_name: str) -> bool:
        """Set a model as the active OCR model by copying it to model.mlmodel."""
        model_path = Path(self.MODELS_DIR) / f"{model_name}.mlmodel"
        active_model_path = Path(self.MODELS_DIR) / "model.mlmodel"

        if not model_path.exists():
            return False

        # Backup current model
        if active_model_path.exists():
            backup_path = Path(self.MODELS_DIR) / f"model_backup_{int(time.time())}.mlmodel"
            shutil.copy(str(active_model_path), str(backup_path))

        # Copy new model as active
        shutil.copy(str(model_path), str(active_model_path))
        logging.info(f"Activated model: {model_name}")

        return True


# Global instance
kraken_training_service = KrakenTrainingService()
