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
    epoch_time: float = 0  # Time for current epoch in seconds
    training_speed: float = 0.0  # Iterations per second (e.g., 29.63)
    recent_logs: list = None  # Last N lines of raw training output for terminal UI

    def __post_init__(self):
        if self.epoch_history is None:
            self.epoch_history = []
        if self.recent_logs is None:
            self.recent_logs = []

    @staticmethod
    def time_str_to_seconds(time_str: str) -> float:
        """Convert H:MM:SS or M:SS to seconds."""
        parts = time_str.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            pass
        return 0

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
            "recent_logs": self.recent_logs[-50:] if self.recent_logs else [],
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

    MIN_LINES_FINETUNE = 50    # Fine-tuning from existing model
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

    def get_training_stats(self, texts_handler, project_id: int = None, project_ids: list = None) -> dict:
        """Get training statistics from DB (all curated data)."""
        curated_stats = texts_handler.get_curated_training_stats(target=None, project_id=project_id, project_ids=project_ids)
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
        - Use --resize union for fine-tuning (preserves base model weights)
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

        # Learning rate for fine-tuning (Kraken docs recommend 0.0001)
        cmd.extend(["-r", "0.0001"])

        # NOTE: --augment requires albumentations package which is not installed
        # Skip augmentation for now - can be added later if albumentations is installed
        # cmd.append("--augment")

        # Note: --workers was removed in kraken 6.x

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

        # In kraken 6.x, device is set via KRAKEN_DEVICE env var (no CLI flag on ketos train)
        # In kraken 5.x, use -d flag
        if resolved_device and resolved_device != "cpu":
            if KRAKEN_VERSION[0] >= 6:
                logging.info(f"Using {resolved_device} via KRAKEN_DEVICE env var (Kraken {KRAKEN_VERSION[0]}.x)")
            else:
                cmd.extend(["-d", resolved_device])
                logging.info(f"Using {resolved_device} (Kraken {KRAKEN_VERSION[0]}.x)")
        else:
            logging.info("Training on CPU")

        # Add base model for fine-tuning if provided
        # Use --resize union to preserve base model's learned character weights
        # while adding output neurons for new characters in the training data.
        # This avoids catastrophic forgetting when training data has characters
        # the base model doesn't know (e.g. SAA model: 105 chars, data: 127 chars).
        logging.info(f"[_build_training_command] base_model={base_model}")
        logging.info(f"[_build_training_command] base_model exists: {base_model and os.path.exists(base_model)}")
        logging.info(f"[_build_training_command] MODELS_DIR={self.MODELS_DIR}")
        if base_model and os.path.exists(base_model):
            logging.info(f"[_build_training_command] Using provided base_model: {base_model}")
            cmd.extend(["-i", base_model])
            cmd.extend(["--resize", "union"])
        else:
            # Use active model as base for fine-tuning
            active_name = self.get_active_model_name()
            if active_name:
                active_path = f"{self.MODELS_DIR}/{active_name}.mlmodel"
                if os.path.exists(active_path):
                    logging.info(f"[_build_training_command] Using active model as base: {active_name}")
                    cmd.extend(["-i", active_path])
                    cmd.extend(["--resize", "union"])

        # Add training data pattern
        cmd.append(training_pattern)

        logging.info(f"Built training command for Kraken {KRAKEN_VERSION[0]}.{KRAKEN_VERSION[1]}.{KRAKEN_VERSION[2]}")
        logging.info(f"Training command: {' '.join(cmd)}")

        return cmd, resolved_device

    def export_training_data(self, texts_handler, project_id: int = None, project_ids: list = None) -> dict:
        """
        Export curated texts as training data (line images + ground truth).
        Uses pre-persisted data from kraken-training/ (or per-project subdir) if available,
        falls back to on-the-fly generation from DB.
        Supports multiple project_ids: aggregates data from all specified projects.
        """
        # If multiple project_ids, aggregate data from each
        if project_ids and len(project_ids) > 1:
            return self._export_multi_project(texts_handler, project_ids)

        # Single project (or all projects)
        effective_pid = project_ids[0] if project_ids and len(project_ids) == 1 else project_id
        logging.info(f"Exporting training data from curated texts (project_id={effective_pid})...")

        if effective_pid is not None:
            training_dir = Path(self.TRAINING_DATA_DIR) / str(effective_pid)
        else:
            training_dir = Path(self.TRAINING_DATA_DIR)

        # Check for pre-persisted training data
        existing_gt_files = list(training_dir.glob("*.gt.txt")) if training_dir.exists() else []
        if existing_gt_files:
            # Count unique text IDs and total lines from persisted data
            text_ids = set()
            for gt_file in existing_gt_files:
                # Filename format: text{id}_line{N}.gt.txt
                name = gt_file.stem.replace(".gt", "")
                parts = name.split("_line")
                if parts:
                    try:
                        tid = int(parts[0].replace("text", ""))
                        text_ids.add(tid)
                    except ValueError:
                        pass

            exported_lines = len(existing_gt_files)
            exported_texts = len(text_ids)
            exported_text_ids = sorted(text_ids)

            logging.info(f"Using pre-persisted training data: {exported_lines} lines from {exported_texts} texts")
            return {
                "exported_lines": exported_lines,
                "exported_texts": exported_texts,
                "exported_text_ids": exported_text_ids,
                "training_dir": str(training_dir),
                "skipped_vlm": 0
            }

        # Fallback: generate on the fly (for texts curated before persistence was added)
        logging.info("No pre-persisted data found, generating from DB...")

        exported_lines = 0
        exported_texts = 0
        exported_text_ids = []

        curated_data = texts_handler.get_curated_training_data_for("kraken", project_id=effective_pid)

        skipped_vlm = 0
        for text_data in curated_data:
            text_id = text_data["text_id"]
            image_path = text_data["image_path"]
            lines = text_data["lines"]
            boxes = text_data["boxes"]

            if not os.path.exists(image_path):
                logging.warning(f"Image not found: {image_path}")
                continue

            if len(boxes) != len(lines):
                skipped_vlm += 1
                logging.info(f"Skipping text {text_id}: {len(boxes)} boxes != {len(lines)} lines (VLM-style)")
                continue

            try:
                full_image = Image.open(image_path)

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
                    line_image.save(str(training_dir / line_filename), "PNG")

                    gt_filename = f"text{text_id}_line{i:03d}.gt.txt"
                    with open(training_dir / gt_filename, "w", encoding="utf-8") as f:
                        f.write(line_text.strip())

                    exported_lines += 1

                exported_texts += 1
                exported_text_ids.append(text_id)

            except Exception as e:
                logging.error(f"Error processing text {text_id}: {e}")
                continue

        if skipped_vlm > 0:
            logging.warning(f"Skipped {skipped_vlm} texts with VLM-style boxes")
        logging.info(f"Exported {exported_lines} lines from {exported_texts} texts")

        return {
            "exported_lines": exported_lines,
            "exported_texts": exported_texts,
            "exported_text_ids": exported_text_ids,
            "training_dir": str(training_dir),
            "skipped_vlm": skipped_vlm
        }

    def _export_multi_project(self, texts_handler, project_ids: list) -> dict:
        """Aggregate training data from multiple projects into a shared directory."""
        merged_dir = Path(self.TRAINING_DATA_DIR) / "merged"
        merged_dir.mkdir(parents=True, exist_ok=True)

        total_lines = 0
        total_texts = 0
        all_text_ids = []
        total_skipped = 0

        for pid in project_ids:
            result = self.export_training_data(texts_handler, project_id=pid)
            src_dir = Path(result["training_dir"])

            # Copy/symlink files into merged directory
            for f in src_dir.glob("*.png"):
                gt = f.with_suffix("").with_suffix(".gt.txt")
                dest_png = merged_dir / f.name
                dest_gt = merged_dir / gt.name
                if not dest_png.exists():
                    import shutil
                    shutil.copy2(str(f), str(dest_png))
                    if gt.exists():
                        shutil.copy2(str(gt), str(dest_gt))

            total_lines += result["exported_lines"]
            total_texts += result["exported_texts"]
            all_text_ids.extend(result["exported_text_ids"])
            total_skipped += result.get("skipped_vlm", 0)

        logging.info(f"Merged training data from {len(project_ids)} projects: {total_lines} lines, {total_texts} texts")
        return {
            "exported_lines": total_lines,
            "exported_texts": total_texts,
            "exported_text_ids": all_text_ids,
            "training_dir": str(merged_dir),
            "skipped_vlm": total_skipped,
        }

    TARGET_LINE_HEIGHT = 30  # Normalize training images to this height (matches SAA model scale)
    MIN_IMAGE_WIDTH = 30     # Remove images narrower than this (cause Kraken dewarping crashes)
    MIN_IMAGE_HEIGHT = 20    # Remove images shorter than this

    def _normalize_image_heights(self, training_dir: str) -> int:
        """
        Prepare training images:
        1. Remove tiny images that crash Kraken's dewarping (inhomogeneous array error)
        2. Downscale tall images to match the base model's expected line height

        Returns the number of images resized.
        """
        resized = 0
        removed = 0
        target_h = self.TARGET_LINE_HEIGHT
        # Only downscale images taller than 1.5x the target (e.g. >45px when target=30)
        threshold = int(target_h * 1.5)
        training_path = Path(training_dir)

        for png_file in training_path.glob("*.png"):
            try:
                img = Image.open(str(png_file))
                w, h = img.size

                # Remove tiny images that crash Kraken's dewarping
                if w < self.MIN_IMAGE_WIDTH or h < self.MIN_IMAGE_HEIGHT:
                    gt_file = png_file.with_suffix("").with_suffix(".gt.txt")
                    png_file.unlink()
                    if gt_file.exists():
                        gt_file.unlink()
                    removed += 1
                    continue

                if h <= threshold:
                    continue  # Already close enough — don't upscale

                # Downscale preserving aspect ratio
                new_w = max(1, round(w * target_h / h))
                img_resized = img.resize((new_w, target_h), Image.LANCZOS)
                img_resized.save(str(png_file), "PNG")
                resized += 1
            except Exception as e:
                logging.warning(f"Failed to process {png_file.name}: {e}")

        if removed > 0:
            logging.info(f"Removed {removed} tiny images (< {self.MIN_IMAGE_WIDTH}x{self.MIN_IMAGE_HEIGHT}px) from {training_dir}")
        if resized > 0:
            logging.info(f"Normalized {resized} images to height={target_h}px in {training_dir}")
        return resized

    async def start_training(
        self,
        texts_handler,
        epochs: int = 500,  # High limit - early stopping will decide when to stop
        model_name: Optional[str] = None,
        base_model: Optional[str] = None,
        batch_size: int = 1,
        device: str = "auto",
        patience: int = None,
        progress_callback: Optional[Callable] = None,
        project_id: int = None,
        project_ids: list = None,
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
            self.progress.recent_logs = []
            self._pending_metric = None

            if progress_callback:
                await progress_callback(self.progress)

            # Export training data
            logging.info("Exporting training data...")
            export_result = self.export_training_data(texts_handler, project_id=project_id, project_ids=project_ids)
            logging.info(f"Export result: {export_result}")

            # Copy training data to a normalized directory so originals stay intact
            training_dir = export_result.get("training_dir", self.TRAINING_DATA_DIR)
            norm_dir = Path(self.TRAINING_DATA_DIR) / "_normalized"
            if norm_dir.exists():
                shutil.rmtree(str(norm_dir))
            norm_dir.mkdir(parents=True)
            for f in Path(training_dir).glob("*"):
                shutil.copy2(str(f), str(norm_dir / f.name))

            # Normalize image heights to match base model's expected scale
            resized_count = self._normalize_image_heights(str(norm_dir))
            if resized_count > 0:
                self.progress.message = f"Normalized {resized_count} images to {self.TARGET_LINE_HEIGHT}px height"
                if progress_callback:
                    await progress_callback(self.progress)
            # Use normalized dir for training
            training_dir = str(norm_dir)

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

            # training_dir is already set to the normalized copy above

            # Build ketos train command - version aware
            # For PNG + .gt.txt pairs, use default "path" format (no -f flag)
            cmd, resolved_device = self._build_training_command(
                output_path=str(output_path),
                epochs=epochs,
                base_model=base_model,
                training_pattern=f"{training_dir}/*.png",
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
            # Kraken 6.x uses env var for device selection
            if resolved_device and KRAKEN_VERSION[0] >= 6:
                train_env["KRAKEN_DEVICE"] = resolved_device

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,  # Unbuffered binary mode
                env=train_env
            )

            # Monitor progress — read byte-by-byte and split on \r or \n
            # because ketos/PyTorch Lightning uses \r for progress bar updates
            # and readline() would block forever waiting for \n.
            # Raw output is written directly to sys.stderr for live terminal display.
            import sys
            recent_logs = self.progress.recent_logs
            line_buffer = []
            while True:
                ch = self.process.stdout.read(1)
                if not ch:
                    # Process ended — flush remaining buffer
                    if line_buffer:
                        line_text = b"".join(line_buffer).decode("utf-8", errors="replace").strip()
                        if line_text:
                            recent_logs.append(line_text)
                            if len(recent_logs) > 100:
                                del recent_logs[:len(recent_logs) - 100]
                            self._parse_progress(line_text)
                        try:
                            sys.stderr.buffer.write(b"".join(line_buffer) + b"\n")
                            sys.stderr.buffer.flush()
                        except Exception:
                            pass
                    break

                # Echo raw byte to terminal for live output
                try:
                    sys.stderr.buffer.write(ch)
                    if ch in (b"\n", b"\r"):
                        sys.stderr.buffer.flush()
                except Exception:
                    pass

                if ch in (b"\n", b"\r"):
                    if line_buffer:
                        line_text = b"".join(line_buffer).decode("utf-8", errors="replace").strip()
                        line_buffer = []
                        if line_text:
                            recent_logs.append(line_text)
                            if len(recent_logs) > 100:
                                del recent_logs[:len(recent_logs) - 100]
                            self._parse_progress(line_text)

                            if progress_callback:
                                await progress_callback(self.progress)

                            # Custom early stopping check
                            if self._should_early_stop():
                                logging.info(f"Early stopping: no improvement for {self._patience} consecutive epochs")
                                self.progress.early_stopped = True
                                self.progress.message = f"Early stopped at epoch {self.progress.epoch} (no improvement for {self._patience} epochs)"
                                self.process.terminate()
                                break
                else:
                    line_buffer.append(ch)

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
                # Ketos saves checkpoints as either:
                #   {output}_best.mlmodel  (best model)
                #   {output}_0.mlmodel, {output}_1.mlmodel  (per-epoch, kraken 6.x)
                #   {output}_0, {output}_1  (per-epoch, kraken 5.x)
                best_model = Path(f"{output_path}_best.mlmodel")
                if best_model.exists():
                    shutil.move(str(best_model), str(output_path))
                    logging.info(f"Renamed best model to {output_path}")
                elif not output_path.exists():
                    # Fall back to the last epoch model — match both naming conventions
                    def get_epoch_num(path):
                        try:
                            name = str(path.name)
                            # Extract trailing number after last _
                            num_str = name.split('_')[-1].replace('.mlmodel', '')
                            return int(num_str)
                        except (ValueError, IndexError):
                            return -1

                    epoch_models = [
                        f for f in Path(self.MODELS_DIR).iterdir()
                        if f.name.startswith(f"{model_name}.mlmodel_") and get_epoch_num(f) >= 0
                    ]
                    if epoch_models:
                        epoch_models.sort(key=get_epoch_num)
                        last_model = epoch_models[-1]
                        shutil.move(str(last_model), str(output_path))
                        logging.info(f"Renamed {last_model.name} (epoch {get_epoch_num(last_model)}) to {output_path}")

                # Clean up all intermediate epoch checkpoint files
                for f in Path(self.MODELS_DIR).iterdir():
                    if f.name.startswith(f"{model_name}.mlmodel_"):
                        f.unlink()
                        logging.info(f"Cleaned up intermediate model: {f.name}")

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
                # Capture last output lines for error diagnosis
                tail = "\n".join(recent_logs[-15:])
                error_detail = f"Training process exited with code {self.process.returncode}.\nLast output:\n{tail}"
                self.progress.status = TrainingStatus.FAILED
                self.progress.message = "Training failed"
                self.progress.error = error_detail
                self.progress.completed_at = datetime.now().isoformat()
                logging.error(f"=== Training failed: exit code {self.process.returncode} ===")
                logging.error(f"Last ketos output:\n{tail}")
                return {
                    "success": False,
                    "error": error_detail
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

    # Tracks state for multi-line metric parsing
    _pending_metric = None
    _expect_word_accuracy = False  # True when we just parsed val_accuracy, next bare number is word_accuracy

    def _parse_progress(self, line: str):
        """Parse Kraken/ketos training output for progress info.

        Ketos output format varies by terminal settings. Common patterns:

        Full progress bar (when rich works):
            stage 0/500 ---- 79/79 0:00:44 · 0:00:00 1.86it/s val_accuracy:
            0.772
            val_word_accurac…
            0.427

        Stripped output (TERM=dumb, \r fragments):
            0:00:00                  0.684
            0.440

        In the stripped format, the first number after time is val_accuracy,
        the next bare decimal is val_word_accuracy.
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

        # Skip noise lines
        if line.startswith("Seed set to") or line.startswith("|") or line.startswith("+"):
            return

        # --- Handle pending metric from previous line ---
        if self._pending_metric:
            value_match = re.search(r"(\d+\.?\d*)\s*$", line)
            if value_match:
                value = float(value_match.group(1))
                metric = self._pending_metric
                if metric == "val_accuracy":
                    if value <= 1.0:  # Accuracy must be 0-1
                        self.progress.val_accuracy = value
                        self.progress.accuracy = value
                        self._expect_word_accuracy = True
                    else:
                        logging.debug(f"Ignoring pending val_accuracy {value} (> 1.0, likely loss)")
                elif metric == "accuracy":
                    if value <= 1.0:
                        self.progress.accuracy = value
                elif metric == "loss":
                    self.progress.loss = value
                elif metric == "word_accuracy":
                    if value <= 1.0:
                        self.progress.word_accuracy = value
                    self._expect_word_accuracy = False
            self._pending_metric = None
            return

        # --- Handle bare decimal: expect word accuracy after val_accuracy ---
        # Pattern: a line that is just a decimal number (e.g. "0.440" or "-0.038")
        # Kraken word accuracy can be negative (normalized metric), so allow minus sign.
        # Reject values > 1.0 (likely loss values like 865.376)
        bare_decimal = re.match(r"^\s*(-?\d+\.?\d*)\s*$", line)
        if bare_decimal and self._expect_word_accuracy:
            val = float(bare_decimal.group(1))
            if val <= 1.0:
                self.progress.word_accuracy = max(0.0, val)  # Clamp negatives to 0 for display
            else:
                # Value > 1.0 is not a valid accuracy — likely a loss value
                logging.debug(f"Ignoring bare decimal {val} as word_accuracy (> 1.0)")
            self._expect_word_accuracy = False
            return

        # --- Stripped format: "0:00:00                  0.684" ---
        # Time + whitespace + decimal value (no labels) — val_accuracy
        # Or: "0:00:30                   0.781" with actual epoch time
        stripped_match = re.match(r"^\s*(\d+:\d{2}:\d{2})\s+(\d+\.\d+)\s*$", line)
        if stripped_match:
            time_str = stripped_match.group(1)
            val = float(stripped_match.group(2))

            # Values > 1.0 are loss values (e.g. "0:00:00  15.019"), not accuracy
            if val > 1.0:
                self.progress.loss = val
                return

            # Detect new epoch: a new time+accuracy pair means a new epoch completed
            # (ketos outputs this once per epoch at validation end)
            if self.progress.epoch < 0:
                self.progress.epoch = 0
            elif val != self.progress.val_accuracy:
                # New accuracy value = new epoch
                already_recorded = any(
                    e["epoch"] == self.progress.epoch for e in self.progress.epoch_history
                )
                if not already_recorded:
                    self._record_epoch()
                self.progress.epoch += 1

            # Parse epoch time — "0:00:30" means 30 seconds
            # But "0:00:00" is typically the ETA, not duration.
            # Use non-zero times as epoch duration.
            if time_str != "0:00:00":
                self.progress.epoch_time = TrainingProgress.time_str_to_seconds(time_str)

            self.progress.val_accuracy = val
            self.progress.accuracy = val
            self._expect_word_accuracy = True
            return

        # --- Full format: "stage X/Y --- N/N H:MM:SS · H:MM:SS Speed val_accuracy:" ---
        epoch_match = re.search(r"(?:stage|epoch)\s*(\d+)(?:/(\d+))?", line, re.I)
        if epoch_match:
            new_epoch = int(epoch_match.group(1))
            if epoch_match.group(2):
                self.progress.total_epochs = int(epoch_match.group(2))

            # If epoch number advanced, record the previous epoch's metrics
            if new_epoch > self.progress.epoch and self.progress.epoch >= 0:
                self._record_epoch()
                # Reset inter-epoch state so stale flags don't leak into the new epoch
                self._expect_word_accuracy = False

            self.progress.epoch = new_epoch

        # Parse batch progress: "79/79" pattern after stage
        batch_match = re.search(r"(?:stage\s*\d+/\d+)[^0-9]*(\d+)/(\d+)", line, re.I)
        if batch_match:
            prev_batch = self.progress.batch_current
            self.progress.batch_current = int(batch_match.group(1))
            self.progress.batch_total = int(batch_match.group(2))
            # Log batch progress at intervals (every 25% or when complete)
            total = self.progress.batch_total
            current = self.progress.batch_current
            if total > 0 and (current == total or (current % max(1, total // 4) == 0 and current != prev_batch)):
                pct = round(current / total * 100)
                logging.info(f"  Epoch {self.progress.epoch} | batch {current}/{total} ({pct}%)")

        # Parse epoch time: first H:MM:SS is epoch duration, second is ETA
        time_matches = re.findall(r"(\d+:\d{2}:\d{2})", line)
        if time_matches:
            self.progress.epoch_time = TrainingProgress.time_str_to_seconds(time_matches[0])

        # Parse training speed: "1.86it/s"
        speed_match = re.search(r"(\d+\.?\d*)\s*it/s", line, re.I)
        if speed_match:
            self.progress.training_speed = float(speed_match.group(1))

        # Parse val_accuracy on same line
        acc_match = re.search(r"val_accuracy[:\s=]+([0-9.]+)", line, re.I)
        if acc_match:
            val = float(acc_match.group(1))
            self.progress.accuracy = val
            self.progress.val_accuracy = val
            self._expect_word_accuracy = True
        else:
            acc_match2 = re.search(r"(?<!val_)accuracy[:\s=]+([0-9.]+)", line, re.I)
            if acc_match2:
                self.progress.accuracy = float(acc_match2.group(1))

        # Parse word accuracy: "val_word_accur…" or "val_word_accuracy"
        word_acc_match = re.search(r"val_word_accur[^\d]*([0-9.]+)", line, re.I)
        if word_acc_match:
            self.progress.word_accuracy = float(word_acc_match.group(1))
            self._expect_word_accuracy = False

        # Parse loss (matches "loss:", "train_loss:", "train_loss_step:" etc.)
        loss_match = re.search(r"(?:train_)?loss(?:_step)?[:\s=]+([0-9.]+)", line, re.I)
        if loss_match:
            self.progress.loss = float(loss_match.group(1))

        # Detect label at end of line without value (wrapped to next line)
        if re.search(r"val_accuracy[:\s]*$", line, re.I):
            self._pending_metric = "val_accuracy"
        elif re.search(r"val_word_accur[:\s\u2026]*$", line, re.I):
            self._pending_metric = "word_accuracy"
        elif re.search(r"(?<!val_)accuracy[:\s]*$", line, re.I):
            self._pending_metric = "accuracy"
        elif re.search(r"(?:train_)?loss(?:_(?:step|epoch?))?[:\s\u2026]*$", line, re.I):
            self._pending_metric = "loss"
            self._expect_word_accuracy = False  # Loss label cancels word_accuracy expectation

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

        # Format epoch time
        t = self.progress.epoch_time
        time_fmt = f"{int(t//60)}:{int(t%60):02d}" if t else "-"

        # Format word accuracy
        word_acc = f", word_acc={self.progress.word_accuracy:.4f}" if self.progress.word_accuracy else ""

        pct = round((self.progress.epoch + 1) / self.progress.total_epochs * 100, 1) if self.progress.total_epochs else 0
        logging.info(
            f"Epoch {self.progress.epoch}/{self.progress.total_epochs} ({pct}%) | "
            f"char_acc={current_acc:.4f}{word_acc} | "
            f"best={self.progress.best_accuracy:.4f} | "
            f"time={time_fmt} | "
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
        model_name = self.progress.model_name
        if self.process:
            self.process.terminate()
        self.progress.status = TrainingStatus.CANCELLED
        self.progress.message = "Training cancelled"
        self.progress.completed_at = datetime.now().isoformat()

        # Clean up intermediate epoch checkpoint files
        if model_name:
            for f in Path(self.MODELS_DIR).iterdir():
                if f.name.startswith(f"{model_name}.mlmodel_"):
                    f.unlink()
                    logging.info(f"Cleaned up intermediate model: {f.name}")

    # Cache: { model_path: { "mtime": float, "metrics": dict } }
    _metrics_cache: dict = {}

    def _extract_model_metrics(self, model_path: str) -> dict:
        """Extract accuracy, epochs, and other metrics from a Kraken .mlmodel file.
        Results are cached by file path + modification time to avoid reloading."""
        # Check cache first
        try:
            mtime = os.path.getmtime(model_path)
        except OSError:
            return {}

        cached = self._metrics_cache.get(model_path)
        if cached and cached["mtime"] == mtime:
            return cached["metrics"]

        metrics = {}
        try:
            from kraken.lib.models import load_any
            model = load_any(model_path)

            # Extract from model metadata
            if hasattr(model, 'nn'):
                nn = model.nn
                if hasattr(nn, 'hyper_params'):
                    hp = nn.hyper_params
                    if isinstance(hp, dict):
                        metrics['epochs'] = hp.get('completed_epochs', hp.get('epochs', None))
                        metrics['learning_rate'] = hp.get('lrate', hp.get('lr', None))
                if hasattr(nn, 'user_metadata'):
                    um = nn.user_metadata
                    if isinstance(um, dict):
                        metrics['accuracy'] = um.get('accuracy', None)
                        metrics['word_accuracy'] = um.get('word_accuracy', None)
                if hasattr(nn, 'seg_type'):
                    metrics['type'] = str(nn.seg_type)
                if hasattr(nn, 'codec') and nn.codec:
                    metrics['charset_size'] = len(nn.codec.c2l) if hasattr(nn.codec, 'c2l') else None

            if hasattr(model, 'accuracy'):
                metrics['accuracy'] = model.accuracy
            if hasattr(model, 'hyper_params'):
                hp = model.hyper_params
                if isinstance(hp, dict):
                    metrics['epochs'] = hp.get('completed_epochs', hp.get('epochs', metrics.get('epochs')))

        except Exception as e:
            logging.debug(f"Could not extract metrics from {model_path}: {e}")

        # Store in cache
        self._metrics_cache[model_path] = {"mtime": mtime, "metrics": metrics}
        return metrics

    def _auto_register_model(self, name: str, path: str, metrics: dict):
        """Add a model to registry.json so future lookups skip model loading."""
        registry_path = Path(self.MODELS_DIR) / "registry.json"
        try:
            registry = []
            if registry_path.exists():
                with open(registry_path, "r") as f:
                    registry = json.load(f)
            # Don't duplicate
            if any(e["name"] == name for e in registry):
                return
            entry = {"name": name, "path": path}
            for key in ("accuracy", "word_accuracy", "epochs", "charset_size", "learning_rate"):
                if metrics.get(key) is not None:
                    entry[key] = metrics[key]
            registry.append(entry)
            with open(registry_path, "w") as f:
                json.dump(registry, f, indent=2)
            logging.info(f"Auto-registered Kraken model: {name}")
        except Exception as e:
            logging.warning(f"Could not auto-register model {name}: {e}")

    def _load_registry(self) -> dict:
        """Load registry.json and index by model name for fast lookup."""
        registry_path = Path(self.MODELS_DIR) / "registry.json"
        if registry_path.exists():
            try:
                with open(registry_path, "r") as f:
                    entries = json.load(f)
                return {e["name"]: e for e in entries}
            except Exception:
                pass
        return {}

    def get_models(self) -> List[dict]:
        """List available trained models with metrics.

        Uses registry.json for metrics when available (instant),
        only loads .mlmodel files as a fallback for unregistered models.
        """
        models = []
        models_dir = Path(self.MODELS_DIR)
        registry = self._load_registry()

        for model_path in models_dir.glob("*.mlmodel"):
            stat = model_path.stat()
            name = model_path.stem
            model_info = {
                "name": name,
                "path": str(model_path),
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat()
            }

            # Fast path: use registry metadata (no model loading)
            if name in registry:
                reg = registry[name]
                if reg.get("accuracy") is not None:
                    model_info["accuracy"] = reg["accuracy"]
                if reg.get("word_accuracy") is not None:
                    model_info["word_accuracy"] = reg["word_accuracy"]
                if reg.get("epochs") is not None:
                    model_info["epochs"] = reg["epochs"]
                if reg.get("charset_size") is not None:
                    model_info["charset_size"] = reg["charset_size"]
                if reg.get("learning_rate") is not None:
                    model_info["learning_rate"] = reg["learning_rate"]
            else:
                # Slow path: load model to extract metrics (only for pre-existing models)
                logging.info(f"Loading model metrics (not in registry): {name}")
                metrics = self._extract_model_metrics(str(model_path))
                model_info.update(metrics)
                # Auto-register so future calls are instant
                self._auto_register_model(name, str(model_path), metrics)

            models.append(model_info)

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
