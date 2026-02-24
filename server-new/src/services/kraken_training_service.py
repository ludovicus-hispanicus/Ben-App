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
    epoch_history: list = None
    best_accuracy: float = 0.0
    no_improve_count: int = 0
    early_stopped: bool = False
    # New fields for enhanced training metrics
    word_accuracy: float = 0.0  # val_word_accuracy from ketos
    batch_current: int = 0  # Current batch in epoch (e.g., 918 of 918)
    batch_total: int = 0  # Total batches per epoch
    epoch_time: str = ""  # Time for current epoch (e.g., "0:00:54")
    training_speed: float = 0.0  # Iterations per second (e.g., 29.63)

    def __post_init__(self):
        if self.epoch_history is None:
            self.epoch_history = []

    def to_dict(self):
        return {
            "status": self.status.value,
            "current_epoch": self.epoch,  # Frontend expects current_epoch
            "total_epochs": self.total_epochs,
            "accuracy": self.accuracy,
            "val_accuracy": self.val_accuracy,
            "word_accuracy": self.word_accuracy,
            "loss": self.loss,
            "eta_seconds": self.eta_seconds,
            "message": self.message,
            "model_name": self.model_name,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "epoch_history": self.epoch_history,
            "best_accuracy": self.best_accuracy,
            "no_improve_count": self.no_improve_count,
            "early_stopped": self.early_stopped,
            "batch_current": self.batch_current,
            "batch_total": self.batch_total,
            "epoch_time": self.epoch_time,
            "training_speed": self.training_speed,
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

    MIN_LINES_FINETUNE = 100   # Fine-tuning from existing model
    MIN_LINES_SCRATCH = 500    # Training from scratch (no base model)
    MIN_EPOCHS = 20  # Don't early stop before this many epochs (per Kraken docs)
    PATIENCE = 10  # Stop if no improvement for this many consecutive epochs (was 5, docs recommend 10)
    _pending_metric = None  # Tracks when a metric label appears without its value on the same line

    def __init__(self):
        # Use STORAGE_PATH environment variable for local storage
        storage_path = os.environ.get("STORAGE_PATH", "data")
        self.TRAINING_DATA_DIR = os.path.join(storage_path, "kraken-training")
        # Models directory - use cured_models in src folder (same as KrakenOcrClient)
        self.MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cured_models")
        self.TRAINING_HISTORY_FILE = os.path.join(storage_path, "kraken_training_history.json")
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
        curated_stats = texts_handler.get_curated_training_stats(target="kraken")
        total_lines = curated_stats.get("total_lines", 0)
        total_texts = curated_stats.get("curated_texts", 0)
        codec_size = curated_stats.get("codec_size", 0)
        unique_characters = curated_stats.get("unique_characters", [])

        previous_lines = self._training_history.get("previous_lines", 0)
        new_lines = max(0, total_lines - previous_lines)

        return {
            "previous_lines": previous_lines,
            "new_lines": new_lines,
            "total_lines": total_lines,
            "curated_texts": total_texts,
            "codec_size": codec_size,
            "unique_characters": unique_characters,
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
        training_pattern: str,
        batch_size: int = 1,
        device: str = "auto",
    ) -> List[str]:
        """
        Build ketos train command with version-aware flags.
        Supports both Kraken 5.x and 6.x.

        Based on Kraken documentation best practices:
        - Use --augment for data augmentation (essential for small datasets)
        - Use --workers for parallel data loading
        - Use --resize new for fine-tuning (not union/add)
        - Use --precision bf16-mixed on GPU for speedup

        Uses ketos_wrapper.py to patch rich library's clear_live() bug
        that causes 'pop from empty list' error in subprocess environments.
        """
        # Use our wrapper script that patches rich before running ketos
        # This fixes the 'IndexError: pop from empty list' bug in rich.Console.clear_live
        wrapper_path = os.path.join(os.path.dirname(__file__), "ketos_wrapper.py")
        cmd = ["python", wrapper_path, "train"]

        # Output path (same for both versions)
        cmd.extend(["-o", output_path])

        # Number of epochs (same for both versions)
        cmd.extend(["-N", str(epochs)])

        # Use fixed epochs for fine-tuning (early stopping compares against
        # the base model's original accuracy which is measured on different data,
        # so it always considers fine-tuned epochs as "worse")
        # We implement our own early stopping with MIN_EPOCHS and PATIENCE
        cmd.extend(["-q", "fixed"])

        # Learning rate for fine-tuning (docs recommend 0.0001 for fine-tuning)
        cmd.extend(["-r", "0.0001"])

        # NOTE: --augment requires albumentations package which is not installed
        # Skip augmentation for now - can be added later if albumentations is installed
        # cmd.append("--augment")

        # Use multiple workers for faster data loading
        cmd.extend(["--workers", "4"])

        # Batch size
        if batch_size > 1:
            cmd.extend(["-B", str(batch_size)])

        # Force binarization: base models are trained on grayscale (mode L) but
        # our training images may be binary (mode 1). This ensures compatibility.
        cmd.append("--force-binarization")

        # Device selection
        resolved_device = None
        if device == "cpu":
            resolved_device = "cpu"
        elif device == "auto":
            try:
                import torch
                if torch.cuda.is_available():
                    resolved_device = "cuda:0"
            except ImportError:
                pass
            if not resolved_device:
                resolved_device = "cpu"
        else:
            # Specific GPU index (e.g., "0", "1")
            resolved_device = f"cuda:{device}"

        if resolved_device and resolved_device != "cpu":
            if KRAKEN_VERSION[0] >= 6:
                cmd.extend(["--device", resolved_device])
            else:
                cmd.extend(["-d", resolved_device])
            logging.info(f"Using {resolved_device} (Kraken {KRAKEN_VERSION[0]}.x)")
        else:
            logging.info("Training on CPU")

        # Add base model for fine-tuning if provided
        # Use --resize new (not add/union) per Kraken docs:
        # "When fine-tuning, it is recommended to use new mode not union
        # as the network will rapidly unlearn missing labels in the new dataset"
        logging.info(f"[_build_training_command] base_model={base_model}")
        logging.info(f"[_build_training_command] base_model exists: {base_model and os.path.exists(base_model)}")
        logging.info(f"[_build_training_command] MODELS_DIR={self.MODELS_DIR}")
        if base_model and os.path.exists(base_model):
            logging.info(f"[_build_training_command] Using provided base_model: {base_model}")
            cmd.extend(["-i", base_model])
            cmd.extend(["--resize", "new"])
        else:
            # Use active model as base for fine-tuning
            active_name = self.get_active_model_name()
            if active_name:
                active_path = f"{self.MODELS_DIR}/{active_name}.mlmodel"
                if os.path.exists(active_path):
                    logging.info(f"[_build_training_command] Using active model as base: {active_name}")
                    cmd.extend(["-i", active_path])
                    cmd.extend(["--resize", "new"])

        # Add training data pattern
        cmd.append(training_pattern)

        logging.info(f"Built training command for Kraken {KRAKEN_VERSION[0]}.{KRAKEN_VERSION[1]}.{KRAKEN_VERSION[2]}")
        logging.info(f"Training command: {' '.join(cmd)}")

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

        # Get curated texts targeted for Kraken training
        curated_data = texts_handler.get_curated_training_data_for("kraken")

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

                    # Convert to grayscale (mode 'L') for Kraken compatibility
                    # Base Kraken models are trained on grayscale images
                    if line_image.mode != 'L':
                        line_image = line_image.convert('L')

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
        epochs: int = 500,  # High limit - early stopping will decide when to stop
        model_name: Optional[str] = None,
        base_model: Optional[str] = None,
        batch_size: int = 1,
        device: str = "auto",
        patience: int = None,
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
            logging.info(f"=== Starting training: epochs={epochs}, model_name={model_name}, base_model={base_model} ===")
            logging.info(f"=== base_model exists check: {base_model and os.path.exists(base_model)} ===")

            self._patience = patience if patience is not None else self.PATIENCE

            self.progress.status = TrainingStatus.PREPARING
            self.progress.message = "Exporting training data..."
            self.progress.total_epochs = epochs
            self.progress.model_name = model_name
            self.progress.started_at = datetime.now().isoformat()
            self.progress.error = None
            self.progress.completed_at = None
            self.progress.epoch_history = []
            self.progress.best_accuracy = 0.0
            self.progress.no_improve_count = 0
            self.progress.early_stopped = False
            self.progress.epoch = -1  # -1 = not started; ketos uses 0-indexed epochs
            self.progress.accuracy = 0.0
            self.progress.val_accuracy = 0.0
            self.progress.loss = 0.0
            self._pending_metric = None

            if progress_callback:
                await progress_callback(self.progress)

            # Export training data
            logging.info("Exporting training data...")
            export_result = self.export_training_data(texts_handler)
            logging.info(f"Export result: {export_result}")

            min_lines = self.MIN_LINES_FINETUNE if base_model else self.MIN_LINES_SCRATCH
            if export_result["exported_lines"] < min_lines:
                mode = "fine-tuning" if base_model else "training from scratch"
                raise ValueError(
                    f"Not enough training data for {mode}. Need at least {min_lines} lines, "
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
                training_pattern=f"{self.TRAINING_DATA_DIR}/*.png",
                batch_size=batch_size,
                device=device,
            )

            logging.info(f"Starting training with command: {' '.join(cmd)}")

            self.progress.status = TrainingStatus.TRAINING
            self.progress.message = "Training in progress..."

            if progress_callback:
                await progress_callback(self.progress)

            # Run training
            # Set environment variables to disable rich progress bar (causes IndexError in subprocess)
            train_env = os.environ.copy()
            train_env["TERM"] = "dumb"  # Disable fancy terminal features
            train_env["NO_COLOR"] = "1"  # Disable color output
            train_env["PYTHONUNBUFFERED"] = "1"  # Ensure unbuffered output

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=train_env
            )

            # Monitor progress
            for line in iter(self.process.stdout.readline, ''):
                self._parse_progress(line.strip())

                if progress_callback:
                    await progress_callback(self.progress)

                # Custom early stopping check
                if self._should_early_stop():
                    logging.info(f"Early stopping: no improvement for {self._patience} consecutive epochs")
                    self.progress.early_stopped = True
                    self.progress.message = f"Early stopped at epoch {self.progress.epoch} (no improvement for {self._patience} epochs)"
                    self.process.terminate()
                    break

            # Record the final epoch if not yet recorded
            if self.progress.epoch >= 0:
                already_recorded = any(
                    e["epoch"] == self.progress.epoch for e in self.progress.epoch_history
                )
                if not already_recorded:
                    self._record_epoch()

            self.process.wait()

            if self.process.returncode == 0 or self.progress.early_stopped:
                # Ketos saves models as {output}_0.mlmodel, {output}_best.mlmodel, etc.
                # Rename the best model to the expected output path
                best_model = Path(f"{output_path}_best.mlmodel")
                if best_model.exists():
                    shutil.move(str(best_model), str(output_path))
                    logging.info(f"Renamed best model to {output_path}")
                elif not output_path.exists():
                    # Fall back to the last epoch model
                    # Sort numerically by epoch number (not alphabetically!)
                    # Filenames are like: model.mlmodel_0.mlmodel, model.mlmodel_10.mlmodel
                    epoch_models = list(Path(self.MODELS_DIR).glob(f"{model_name}.mlmodel_*.mlmodel"))
                    if epoch_models:
                        # Extract epoch number from filename and sort numerically
                        def get_epoch_num(path):
                            try:
                                # Extract number between last _ and .mlmodel
                                name = path.stem  # e.g., "model.mlmodel_10"
                                return int(name.split('_')[-1])
                            except (ValueError, IndexError):
                                return -1
                        epoch_models.sort(key=get_epoch_num)
                        last_model = epoch_models[-1]
                        shutil.move(str(last_model), str(output_path))
                        logging.info(f"Renamed {last_model} (epoch {get_epoch_num(last_model)}) to {output_path}")

                # Clean up intermediate epoch models
                for f in Path(self.MODELS_DIR).glob(f"{model_name}.mlmodel_*.mlmodel"):
                    f.unlink()
                    logging.info(f"Cleaned up intermediate model: {f}")

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
        """Parse Kraken/ketos training output for progress info.

        Ketos (via rich) may split metric labels from their values across lines
        when the progress bar is long. For example:
            stage 0/50 ━━━━━━━━━━━ 918/918 0:02:16 ... val_accuracy:
            0.005
        We handle this by tracking a pending metric name when the value
        is not on the same line as the label.

        Also parses: batch progress, epoch time, training speed, word accuracy.
        """
        import re

        # DEBUG: Log every line to a file for analysis
        try:
            storage_path = os.environ.get("STORAGE_PATH", "data")
            debug_log_path = os.path.join(storage_path, "ketos_output.log")
            with open(debug_log_path, "a") as debug_file:
                debug_file.write(f"{line}\n")
        except:
            pass

        # Ketos uses \r for progress bar updates; take the last segment after \r
        if '\r' in line:
            line = line.split('\r')[-1]

        # Check if previous line left a metric label waiting for its value
        if self._pending_metric:
            # The value line may have format: "0:00:00                    0.879"
            # or just "0.879" - extract the last number on the line
            value_match = re.search(r"(\d+\.\d+)\s*$", line)
            if value_match:
                value = float(value_match.group(1))
                metric = self._pending_metric
                if metric == "val_accuracy":
                    self.progress.val_accuracy = value
                    self.progress.accuracy = value  # Use val_accuracy as primary
                    logging.info(f"[ACCURACY PARSED] val_accuracy={value} from continuation: {line}")
                elif metric == "accuracy":
                    self.progress.accuracy = value
                elif metric == "loss":
                    self.progress.loss = value
                elif metric == "word_accuracy":
                    self.progress.word_accuracy = value
                    logging.info(f"[WORD ACCURACY PARSED] word_accuracy={value} from continuation: {line}")
                logging.info(f"Parsed {metric}={value} from continuation line")
            self._pending_metric = None

        # Try to parse epoch from "stage X/Y" or "Epoch X"
        epoch_match = re.search(r"(?:stage|epoch)\s*(\d+)(?:/(\d+))?", line, re.I)
        if epoch_match:
            new_epoch = int(epoch_match.group(1))
            if epoch_match.group(2):
                self.progress.total_epochs = int(epoch_match.group(2))

            # If epoch number advanced, record the previous epoch's metrics
            # (epoch >= 0 because ketos uses 0-indexed epochs)
            if new_epoch > self.progress.epoch and self.progress.epoch >= 0:
                self._record_epoch()

            self.progress.epoch = new_epoch

        # Parse batch progress: "1080/1080" pattern (after stage info)
        batch_match = re.search(r"(?:stage\s*\d+/\d+)[^0-9]*(\d+)/(\d+)", line, re.I)
        if batch_match:
            self.progress.batch_current = int(batch_match.group(1))
            self.progress.batch_total = int(batch_match.group(2))

        # Parse epoch time: "0:00:54" pattern (H:MM:SS or M:SS format after batch)
        time_match = re.search(r"(\d+:\d{2}:\d{2})", line)
        if time_match:
            self.progress.epoch_time = time_match.group(1)

        # Parse training speed: "29.63it/s" pattern
        speed_match = re.search(r"(\d+\.?\d*)\s*it/s", line, re.I)
        if speed_match:
            self.progress.training_speed = float(speed_match.group(1))

        # Try to parse accuracy on the same line (works when line isn't wrapped)
        acc_match = re.search(r"val_accuracy[:\s=]+([0-9.]+)", line, re.I)
        if acc_match:
            val = float(acc_match.group(1))
            self.progress.accuracy = val
            self.progress.val_accuracy = val
            logging.info(f"[ACCURACY PARSED] val_accuracy={val} from line: {line[:100]}")
        else:
            # Check for plain accuracy
            acc_match2 = re.search(r"(?<!val_)accuracy[:\s=]+([0-9.]+)", line, re.I)
            if acc_match2:
                self.progress.accuracy = float(acc_match2.group(1))

        # Try to parse word accuracy on the same line
        # Ketos truncates as "val_word_accur…" or "val_word_accuracy"
        word_acc_match = re.search(r"val_word_accur(?:acy)?[:\s=]+([0-9.]+)", line, re.I)
        if word_acc_match:
            self.progress.word_accuracy = float(word_acc_match.group(1))
            logging.info(f"[WORD ACCURACY PARSED] word_accuracy={self.progress.word_accuracy} from line: {line[:100]}")

        # Try to parse loss on the same line
        loss_match = re.search(r"loss[:\s=]+([0-9.]+)", line, re.I)
        if loss_match:
            self.progress.loss = float(loss_match.group(1))

        # Detect if a metric label ends the line without a value (line was wrapped)
        # e.g. "... val_accuracy:" at end of line, value on next line
        if re.search(r"val_accuracy[:\s]*$", line, re.I):
            self._pending_metric = "val_accuracy"
        elif re.search(r"val_word_accur[:\s…]*$", line, re.I):
            self._pending_metric = "word_accuracy"
        elif re.search(r"accuracy[:\s]*$", line, re.I):
            self._pending_metric = "accuracy"
        elif re.search(r"loss[:\s]*$", line, re.I):
            self._pending_metric = "loss"

    def _record_epoch(self):
        """Record the current epoch's metrics in history and check early stopping."""
        epoch_data = {
            "epoch": self.progress.epoch,
            "accuracy": self.progress.accuracy,
            "val_accuracy": self.progress.val_accuracy,
            "word_accuracy": self.progress.word_accuracy,
            "loss": self.progress.loss,
            "epoch_time": self.progress.epoch_time,
            "training_speed": self.progress.training_speed,
        }
        self.progress.epoch_history.append(epoch_data)

        # Custom early stopping logic
        current_acc = self.progress.accuracy
        if current_acc > self.progress.best_accuracy:
            self.progress.best_accuracy = current_acc
            self.progress.no_improve_count = 0
        else:
            self.progress.no_improve_count += 1

        min_epochs_note = ""
        if self.progress.epoch < self.MIN_EPOCHS:
            min_epochs_note = f" (min epochs: {self.progress.epoch + 1}/{self.MIN_EPOCHS})"
        logging.info(
            f"Epoch {self.progress.epoch}: accuracy={current_acc:.4f}, "
            f"best={self.progress.best_accuracy:.4f}, "
            f"no_improve={self.progress.no_improve_count}/{self._patience}{min_epochs_note}"
        )

    def _should_early_stop(self) -> bool:
        """Check if training should be stopped due to no improvement.

        Per Kraken docs: Don't stop before MIN_EPOCHS to give the model
        enough time to converge, especially with data augmentation.
        """
        # Don't early stop before minimum epochs
        if self.progress.epoch < self.MIN_EPOCHS:
            return False
        return self.progress.no_improve_count >= self._patience

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
            "epochs": len(self.progress.epoch_history),
            "accuracy": self.progress.best_accuracy
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

    def get_active_model_name(self) -> str:
        """Get the name of the currently active model from active_model.txt."""
        active_file = Path(self.MODELS_DIR) / "active_model.txt"
        if active_file.exists():
            name = active_file.read_text().strip()
            # Verify the model file actually exists
            if (Path(self.MODELS_DIR) / f"{name}.mlmodel").exists():
                return name
        # Fallback: check if base.mlmodel exists
        if (Path(self.MODELS_DIR) / "base.mlmodel").exists():
            return "base"
        return None

    def get_active_model_info(self) -> dict:
        """Get information about the currently active model."""
        active_name = self.get_active_model_name()

        if not active_name:
            return {
                "name": "No Model",
                "is_pretrained": False,
                "size_mb": 0,
                "last_modified": None
            }

        model_path = Path(self.MODELS_DIR) / f"{active_name}.mlmodel"
        stat = model_path.stat()
        size_mb = round(stat.st_size / 1024 / 1024, 2)
        last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Check registry to see if this is a trained model
        is_pretrained = True
        registry_path = Path(self.MODELS_DIR) / "registry.json"
        if registry_path.exists():
            try:
                with open(registry_path, "r") as f:
                    registry = json.load(f)
                    for model in registry:
                        if model.get("name") == active_name:
                            is_pretrained = False
                            break
            except Exception as e:
                logging.warning(f"Could not read model registry: {e}")

        return {
            "name": active_name,
            "is_pretrained": is_pretrained,
            "size_mb": size_mb,
            "last_modified": last_modified
        }

    def activate_model(self, model_name: str) -> bool:
        """Set a model as the active OCR model by writing its name to active_model.txt."""
        model_path = Path(self.MODELS_DIR) / f"{model_name}.mlmodel"

        if not model_path.exists():
            return False

        active_file = Path(self.MODELS_DIR) / "active_model.txt"
        active_file.write_text(model_name)
        logging.info(f"Activated model: {model_name}")

        return True

    def delete_model(self, model_name: str) -> dict:
        """Delete a model file. Returns {success: bool, error?: str}."""
        # Don't allow deleting the active model
        active_name = self.get_active_model_name()
        if active_name and active_name == model_name:
            return {"success": False, "error": f"Cannot delete the active model '{model_name}'. Activate a different model first."}

        model_path = Path(self.MODELS_DIR) / f"{model_name}.mlmodel"

        if not model_path.exists():
            return {"success": False, "error": f"Model '{model_name}' not found."}

        # Remove from registry if present
        registry_path = Path(self.MODELS_DIR) / "registry.json"
        if registry_path.exists():
            try:
                with open(registry_path, "r") as f:
                    registry = json.load(f)
                # Filter out the deleted model
                registry = [m for m in registry if m.get("name") != model_name]
                with open(registry_path, "w") as f:
                    json.dump(registry, f, indent=2)
            except Exception as e:
                logging.warning(f"Could not update registry: {e}")

        # Delete the file
        model_path.unlink()
        logging.info(f"Deleted model: {model_name}")

        return {"success": True}


# Global instance
kraken_training_service = KrakenTrainingService()
