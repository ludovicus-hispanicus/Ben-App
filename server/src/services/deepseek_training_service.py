"""
DeepSeek-OCR LoRA fine-tuning service.

Trains a LoRA adapter for DeepSeek-OCR (3B) on curated CuReD texts and turns it into an
Ollama model (`deepseek-ocr-<name>`) that CuReD lists with the other Ollama models.

The training itself runs in a separate process (deepseek_training_worker.py), because
Unsloth patches transformers globally on import, and a separate process frees all GPU
memory when it ends.
"""
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from services.training_common import TrainingProgress, TrainingStatus
from services.deepseek_ollama_export import (
    export_adapter_to_ollama, delete_ollama_model, find_ollama, ollama_model_name,
)


class DeepSeekTrainingService:
    """LoRA fine-tuning of DeepSeek-OCR, exported to Ollama."""

    MIN_LINES = 30
    PATIENCE = 2

    BASE_MODELS = {
        "deepseek-ocr": {"hf_id": "unsloth/DeepSeek-OCR", "name": "DeepSeek-OCR 3B"},
    }
    DEFAULT_BASE_MODEL = "deepseek-ocr"

    def __init__(self):
        storage_path = os.environ.get("STORAGE_PATH", "data")
        self.TRAINING_DATA_DIR = os.path.join(storage_path, "deepseek-training")
        self.LORA_ADAPTERS_DIR = os.path.join(storage_path, "deepseek_lora_adapters")
        self.TRAINING_HISTORY_FILE = os.path.join(storage_path, "deepseek_training_history.json")
        self.progress = TrainingProgress(
            status=TrainingStatus.IDLE, epoch=0, total_epochs=0,
            accuracy=0.0, val_accuracy=0.0, loss=0.0, eta_seconds=0, message="",
        )
        self._cancel_requested = False
        self._patience = self.PATIENCE
        Path(self.TRAINING_DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.LORA_ADAPTERS_DIR).mkdir(parents=True, exist_ok=True)
        self._training_history = self._load_training_history()

    @property
    def base_model_dir(self) -> str:
        return os.environ.get("DEEPSEEK_OCR_BASE_DIR") or str(Path.home() / ".cache" / "deepseek_ocr")

    # ------------------------------------------------------------------ #
    #  History, statistics, training data
    # ------------------------------------------------------------------ #

    def _load_training_history(self) -> dict:
        try:
            if os.path.exists(self.TRAINING_HISTORY_FILE):
                with open(self.TRAINING_HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logging.warning(f"Could not load DeepSeek training history: {e}")
        return {"last_training_timestamp": None, "previous_lines": 0, "trained_text_ids": []}

    def _save_training_history(self, trained_lines: int, trained_text_ids: List[int]):
        self._training_history = {
            "last_training_timestamp": datetime.now().isoformat(),
            "previous_lines": trained_lines,
            "trained_text_ids": trained_text_ids,
        }
        try:
            with open(self.TRAINING_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self._training_history, f, indent=2)
        except Exception as e:
            logging.error(f"Could not save DeepSeek training history: {e}")

    def get_training_stats(self, texts_handler, dataset_ids: list = None) -> dict:
        curated = texts_handler.get_curated_training_stats(target="vlm", dataset_ids=dataset_ids)
        total_lines = curated.get("total_lines", 0)
        previous_lines = self._training_history.get("previous_lines", 0)
        return {
            "previous_lines": previous_lines,
            "new_lines": max(0, total_lines - previous_lines),
            "total_lines": total_lines,
            "curated_texts": curated.get("curated_texts", 0),
            "last_training": self._training_history.get("last_training_timestamp"),
        }

    def export_training_data(self, texts_handler, dataset_ids: list = None) -> dict:
        """Copy the curated page images and write manifest.json (image + curated text)."""
        training_dir = Path(self.TRAINING_DATA_DIR)
        for f in training_dir.glob("*"):
            if f.is_file():
                f.unlink()

        items, text_ids = [], []
        for text_data in texts_handler.get_curated_training_data_for("vlm", dataset_ids=dataset_ids):
            text_id, image_path = text_data["text_id"], text_data["image_path"]
            if not os.path.exists(image_path):
                logging.warning(f"Image not found: {image_path}")
                continue
            lines = [line.strip() for line in text_data["lines"] if line.strip()]
            dst = training_dir / f"text{text_id}.png"
            shutil.copy(image_path, dst)
            items.append({"image_path": str(dst), "text_id": text_id, "lines": lines,
                          "ground_truth": "\n".join(lines)})
            text_ids.append(text_id)

        with open(training_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        total_lines = sum(len(item["lines"]) for item in items)
        logging.info(f"Exported {total_lines} lines from {len(items)} texts for DeepSeek-OCR")
        return {"exported_lines": total_lines, "exported_texts": len(items),
                "exported_text_ids": text_ids, "training_dir": str(training_dir)}

    # ------------------------------------------------------------------ #
    #  Entry point
    # ------------------------------------------------------------------ #

    async def start_training(self, texts_handler, epochs: int = 2, model_name: Optional[str] = None,
                             device: str = "auto", patience: int = None, dataset_ids: list = None) -> dict:
        try:
            self._patience = patience if patience is not None else self.PATIENCE
            self._cancel_requested = False
            if not model_name:
                model_name = f"deepseek_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.progress = TrainingProgress(
                status=TrainingStatus.PREPARING, epoch=0, total_epochs=epochs,
                accuracy=0.0, val_accuracy=0.0, loss=0.0, eta_seconds=0,
                message="Preparing training data...", model_name=model_name,
                started_at=datetime.now().isoformat(),
            )
            logging.info(f"=== Starting DeepSeek-OCR LoRA training: epochs={epochs}, model={model_name} ===")

            export_result = self.export_training_data(texts_handler, dataset_ids=dataset_ids)
            if export_result["exported_lines"] < self.MIN_LINES:
                raise ValueError(f"Not enough training data. Need at least {self.MIN_LINES} lines, "
                                 f"got {export_result['exported_lines']}")

            result = await self._run_training(export_result, epochs, model_name, device)
            if result["success"]:
                self._save_training_history(export_result["exported_lines"], export_result["exported_text_ids"])
            return result
        except Exception as e:
            logging.exception(f"=== DeepSeek training error: {e} ===")
            self._set(TrainingStatus.FAILED, message=str(e), error=str(e),
                      completed_at=datetime.now().isoformat())
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Availability, output modes
    # ------------------------------------------------------------------ #

    def availability(self) -> dict:
        """Whether this computer can train DeepSeek-OCR, and why not."""
        missing = [m for m in ("torch", "unsloth", "peft", "gguf", "safetensors")
                   if importlib.util.find_spec(m) is None]
        if getattr(sys, "frozen", False):
            return {"available": False, "reason": "DeepSeek-OCR training runs only when BEn is started from source"}
        if missing:
            return {"available": False, "reason": f"Missing Python packages: {', '.join(missing)}"}
        if not find_ollama():
            return {"available": False, "reason": "Ollama is not installed (needed to run the trained model)"}
        return {"available": True, "reason": None}

    # DeepSeek-OCR is always asked "Free OCR." (see ollama_client); it learns the format
    # of the curated text itself (Markdown bold/italics, line breaks).

    # ------------------------------------------------------------------ #
    #  Training (worker process) and Ollama export
    # ------------------------------------------------------------------ #

    def _set(self, progress_status=None, **fields):
        if progress_status is not None:
            self.progress.status = progress_status
        for k, v in fields.items():
            setattr(self.progress, k, v)

    def _ensure_base_model(self):
        base = Path(self.base_model_dir)
        if (base / "config.json").exists():
            return
        self._set(message="Downloading DeepSeek-OCR from Hugging Face (about 6.3 GB, once)...")
        from huggingface_hub import snapshot_download
        snapshot_download(self.BASE_MODELS["deepseek-ocr"]["hf_id"], local_dir=str(base))

    async def _run_training(self, export_result: dict, epochs: int, model_name: str, device_choice: str) -> dict:
        self._set(TrainingStatus.TRAINING, total_epochs=epochs)
        self._ensure_base_model()

        output_dir = Path(self.LORA_ADAPTERS_DIR) / model_name
        if output_dir.exists():
            shutil.rmtree(output_dir)
        work_dir = Path(self.TRAINING_DATA_DIR)
        cancel_file = work_dir / "cancel"
        cancel_file.unlink(missing_ok=True)
        job = {
            "manifest": str(Path(export_result["training_dir"]) / "manifest.json"),
            "base_model_dir": self.base_model_dir,
            "output_dir": str(output_dir),
            "epochs": epochs,
            "patience": self._patience,
            "cancel_file": str(cancel_file),
        }
        job_path = work_dir / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")

        worker = Path(__file__).with_name("deepseek_training_worker.py")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        if device_choice not in ("auto", "cpu"):
            env["CUDA_VISIBLE_DEVICES"] = str(device_choice)
        log_path = work_dir / "worker.log"
        logging.info(f"Starting DeepSeek-OCR training worker (log: {log_path})")

        result = None
        with open(log_path, "w", encoding="utf-8") as log_file:
            self._process = subprocess.Popen(
                [sys.executable, str(worker), str(job_path)], cwd=str(Path(__file__).parent.parent),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                text=True, encoding="utf-8", errors="replace",
            )
            for line in self._process.stdout:
                log_file.write(line)
                log_file.flush()
                if not line.startswith("@@"):
                    continue
                try:
                    event = json.loads(line[2:])
                except json.JSONDecodeError:
                    continue
                result = self._handle_event(event, epochs) or result
            self._process.wait()

        if self._cancel_requested or (result and result.get("event") == "cancelled"):
            shutil.rmtree(output_dir, ignore_errors=True)
            self._set(TrainingStatus.CANCELLED, message="Training cancelled",
                      completed_at=datetime.now().isoformat())
            return {"success": False, "error": "Cancelled by user"}
        if not result or result.get("event") != "done":
            message = (result or {}).get("message") or f"Training worker stopped (see {log_path})"
            raise RuntimeError(message)
        if not (output_dir / "adapter_model.safetensors").exists():
            raise RuntimeError("Training finished without a saved adapter")

        # Turn the best adapter into an Ollama model
        ollama_name = ollama_model_name(model_name)
        self._set(TrainingStatus.EVALUATING, message=f"Creating the Ollama model {ollama_name}...")
        export_adapter_to_ollama(
            str(output_dir), self.base_model_dir, ollama_name, str(work_dir / "export"),
            log=lambda m: self._set(message=m),
        )

        self._register(str(output_dir), model_name, ollama_name, result, export_result)
        skipped = result.get("skipped", 0)
        self._set(
            TrainingStatus.COMPLETED,
            message=(f"Training completed. In CuReD, choose the Ollama model {ollama_name}."
                     + (f" ({skipped} pages skipped: too long for this GPU)" if skipped else "")),
            completed_at=datetime.now().isoformat(),
        )
        return {"success": True, "adapter_path": str(output_dir), "model_name": model_name,
                "ollama_model": ollama_name, "base_model": self.DEFAULT_BASE_MODEL}

    def _handle_event(self, event: dict, epochs: int) -> Optional[dict]:
        kind = event.get("event")
        if kind == "status":
            self._set(message=event["message"])
        elif kind == "warning":
            logging.warning(event["message"])
        elif kind == "step":
            self._set(epoch=event["epoch"], step=event["step"], total_steps=event["total_steps"],
                      loss=event["loss"], eta_seconds=event["eta_seconds"],
                      message=f"Epoch {event['epoch']}/{epochs}: page {event['step']} of {event['total_steps']}")
        elif kind == "epoch":
            self.progress.epoch_history.append({k: event[k] for k in
                                                ("epoch", "loss", "val_loss", "accuracy", "val_accuracy")})
            self._set(loss=event["loss"], accuracy=event["accuracy"], val_loss=event["val_loss"],
                      val_accuracy=event["val_accuracy"], best_loss=event["best_loss"],
                      best_accuracy=event["best_accuracy"], no_improve_count=event["no_improve_count"],
                      message=(f"Epoch {event['epoch']}/{epochs}: loss {event['loss']:.4f}, "
                               f"val loss {event['val_loss']:.4f}, val acc {event['val_accuracy']:.1%}"))
        elif kind in ("done", "error", "cancelled"):
            if kind == "done" and event.get("epochs_run", epochs) < epochs:
                self.progress.early_stopped = True
            return event
        return None

    def _register(self, adapter_path: str, model_name: str, ollama_name: str, result: dict, export_result: dict):
        registry_path = Path(self.LORA_ADAPTERS_DIR) / "registry.json"
        registry = []
        if registry_path.exists():
            registry = json.loads(registry_path.read_text(encoding="utf-8") or "[]")
        registry = [e for e in registry if e.get("name") != model_name]
        history = result.get("history") or []
        if not isinstance(result.get("best_loss"), (int, float)) or result["best_loss"] == float("inf"):
            result["best_loss"] = None  # no validation page fitted; Infinity is not valid JSON
        registry.append({
            "name": model_name,
            "path": adapter_path,
            "ollama_model": ollama_name,
            "created": datetime.now().isoformat(),
            "epochs": result.get("epochs_run"),
            "base_model": self.DEFAULT_BASE_MODEL,
            "output_mode": "plain",
            "trained_texts": export_result.get("exported_texts"),
            "skipped_texts": result.get("skipped", 0),
            "best_loss": result.get("best_loss"),
            "best_accuracy": result.get("best_accuracy"),
            "final_val_loss": history[-1]["val_loss"] if history else None,
            "final_val_accuracy": history[-1]["val_accuracy"] if history else None,
            "load_in_4bit": result.get("load_in_4bit"),
        })
        registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    def cancel_training(self):
        logging.info("=== Cancelling DeepSeek training ===")
        self._cancel_requested = True
        cancel_file = Path(self.TRAINING_DATA_DIR) / "cancel"
        cancel_file.write_text("cancel", encoding="utf-8")
        # The worker stops at the next page; loading the model cannot be interrupted that way
        process = getattr(self, "_process", None)
        if process and process.poll() is None and self.progress.step == 0:
            process.terminate()

    # ------------------------------------------------------------------ #
    #  Models: each trained model is used in CuReD as its Ollama model
    # ------------------------------------------------------------------ #

    def delete_model(self, adapter_name: str) -> bool:
        adapters = self.get_adapters()
        adapter = next((a for a in adapters if a["name"] == adapter_name), None)
        if not adapter or adapter.get("imported"):
            # Imported models (trained outside BEn, e.g. deepseek-ocr-ahw) are not deleted from here
            return False
        if adapter.get("ollama_model"):
            delete_ollama_model(adapter["ollama_model"])
        path = Path(adapter["path"])
        # Only delete adapters BEn trained itself (registered ones may live elsewhere)
        if path.exists() and Path(self.LORA_ADAPTERS_DIR).resolve() in path.resolve().parents:
            shutil.rmtree(path)
        registry_path = Path(self.LORA_ADAPTERS_DIR) / "registry.json"
        registry_path.write_text(
            json.dumps([a for a in adapters if a["name"] != adapter_name], indent=2), encoding="utf-8")
        logging.info(f"Deleted DeepSeek model: {adapter_name}")
        return True

    def get_adapters(self) -> List[dict]:
        registry_path = Path(self.LORA_ADAPTERS_DIR) / "registry.json"
        if not registry_path.exists():
            return []
        try:
            adapters = json.loads(registry_path.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError:
            return []
        return sorted(adapters, key=lambda x: x.get("created", ""), reverse=True)

    def get_models(self) -> List[dict]:
        return self.get_adapters()


deepseek_training_service = DeepSeekTrainingService()
