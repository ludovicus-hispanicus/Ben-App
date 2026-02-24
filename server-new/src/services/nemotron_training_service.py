"""
Nemotron-Parse LoRA Fine-tuning Service

Handles LoRA fine-tuning for Nemotron-Parse VLM on curated OCR data.
Designed to work on 8GB VRAM GPUs using parameter-efficient training.
"""
import asyncio
import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any
from PIL import Image
import base64
import io

from services.training_common import TrainingStatus, TrainingProgress


class NemotronTrainingService:
    """Service for LoRA fine-tuning of Nemotron-Parse VLM."""

    MIN_LINES = 50  # Lower threshold for LoRA (more data-efficient)
    PATIENCE = 3  # Early stopping patience
    HF_MODEL_ID = "nvidia/NVIDIA-Nemotron-Parse-v1.1"

    def __init__(self):
        # Use STORAGE_PATH environment variable for local storage
        storage_path = os.environ.get("STORAGE_PATH", "data")
        self.TRAINING_DATA_DIR = os.path.join(storage_path, "nemotron-training")
        self.MODELS_DIR = os.path.join(storage_path, "nemotron_models")
        self.LORA_ADAPTERS_DIR = os.path.join(storage_path, "nemotron_lora_adapters")
        self.TRAINING_HISTORY_FILE = os.path.join(storage_path, "nemotron_training_history.json")
        self.progress = TrainingProgress(
            status=TrainingStatus.IDLE,
            epoch=0,
            total_epochs=10,
            accuracy=0.0,
            val_accuracy=0.0,
            loss=0.0,
            eta_seconds=0,
            message=""
        )
        self._model = None
        self._processor = None
        self._training_task = None
        self._cancel_requested = False
        self._ensure_directories()
        self._training_history = self._load_training_history()

    def _ensure_directories(self):
        """Ensure training directories exist."""
        Path(self.TRAINING_DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.MODELS_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.LORA_ADAPTERS_DIR).mkdir(parents=True, exist_ok=True)

    def _load_training_history(self) -> dict:
        """Load training history from file."""
        try:
            if os.path.exists(self.TRAINING_HISTORY_FILE):
                with open(self.TRAINING_HISTORY_FILE, "r") as f:
                    return json.load(f)
        except Exception as e:
            logging.warning(f"Could not load Nemotron training history: {e}")
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
            logging.error(f"Could not save Nemotron training history: {e}")

    def get_training_stats(self, texts_handler) -> dict:
        """Get training statistics with previous/new breakdown."""
        curated_stats = texts_handler.get_curated_training_stats(target="vlm")
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

    def export_training_data(self, texts_handler) -> dict:
        """
        Export curated texts as training data for Nemotron fine-tuning.
        Format: Image files + JSON with ground truth and bounding boxes.
        """
        logging.info("Exporting training data for Nemotron fine-tuning...")

        training_dir = Path(self.TRAINING_DATA_DIR)
        if training_dir.exists():
            for f in training_dir.glob("*"):
                if f.is_file():
                    f.unlink()

        exported_items = []
        exported_texts = 0
        exported_text_ids = []

        curated_data = texts_handler.get_curated_training_data_for("vlm")

        for text_data in curated_data:
            text_id = text_data["text_id"]
            image_path = text_data["image_path"]
            lines = text_data["lines"]
            boxes = text_data["boxes"]

            if not os.path.exists(image_path):
                logging.warning(f"Image not found: {image_path}")
                continue

            try:
                # Copy full image to training directory
                img_filename = f"text{text_id}.png"
                dst_path = training_dir / img_filename
                shutil.copy(image_path, dst_path)

                # Create training item with full page and all lines
                item = {
                    "image_path": str(dst_path),
                    "text_id": text_id,
                    "lines": lines,
                    "boxes": boxes,
                    # Format ground truth as the model expects
                    "ground_truth": self._format_ground_truth(lines, boxes)
                }
                exported_items.append(item)
                exported_texts += 1
                exported_text_ids.append(text_id)

            except Exception as e:
                logging.error(f"Error processing text {text_id}: {e}")
                continue

        # Save manifest
        manifest_path = training_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(exported_items, f, indent=2, ensure_ascii=False)

        total_lines = sum(len(item["lines"]) for item in exported_items)
        logging.info(f"Exported {total_lines} lines from {exported_texts} texts for Nemotron training")

        return {
            "exported_lines": total_lines,
            "exported_texts": exported_texts,
            "exported_text_ids": exported_text_ids,
            "training_dir": str(training_dir)
        }

    def _format_ground_truth(self, lines: List[str], boxes: List[dict]) -> str:
        """
        Format ground truth in Nemotron-Parse output format.
        The model outputs: <x_start><y_start>text<x_end><y_end><class_label>
        """
        # For training, we provide the expected output format
        formatted_lines = []
        for line, box in zip(lines, boxes):
            if not line.strip():
                continue
            # Normalize coordinates to 0-1 range (will be computed during training)
            formatted_lines.append(line.strip())
        return "\n".join(formatted_lines)

    async def start_training(
        self,
        texts_handler,
        epochs: int = 10,
        model_name: Optional[str] = None,
        base_model: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """
        Start LoRA fine-tuning of Nemotron-Parse.

        Args:
            texts_handler: Handler to get training data
            epochs: Number of training epochs
            model_name: Name for the output adapter
            base_model: Optional path to existing LoRA adapter to continue from
            progress_callback: Optional callback for progress updates
        """
        try:
            logging.info(f"=== Starting Nemotron LoRA training: epochs={epochs}, model_name={model_name} ===")

            self._cancel_requested = False
            self.progress = TrainingProgress(
                status=TrainingStatus.PREPARING,
                epoch=0,
                total_epochs=epochs,
                accuracy=0.0,
                val_accuracy=0.0,
                loss=0.0,
                eta_seconds=0,
                message="Preparing training data...",
                model_name=model_name,
                started_at=datetime.now().isoformat()
            )

            if progress_callback:
                await progress_callback(self.progress)

            # Export training data
            export_result = self.export_training_data(texts_handler)

            if export_result["exported_lines"] < self.MIN_LINES:
                raise ValueError(
                    f"Not enough training data. Need at least {self.MIN_LINES} lines, "
                    f"got {export_result['exported_lines']}"
                )

            # Generate model name if not provided
            if not model_name:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                model_name = f"nemotron_lora_{timestamp}"

            self.progress.model_name = model_name
            self.progress.message = "Loading model and preparing LoRA..."

            if progress_callback:
                await progress_callback(self.progress)

            # Run training
            result = await self._run_lora_training(
                export_result,
                epochs,
                model_name,
                base_model,
                progress_callback
            )

            if result["success"]:
                self._save_training_history(
                    trained_lines=export_result["exported_lines"],
                    trained_text_ids=export_result["exported_text_ids"]
                )

            return result

        except Exception as e:
            logging.error(f"=== Nemotron training error: {e} ===")
            import traceback
            traceback.print_exc()
            self.progress.status = TrainingStatus.FAILED
            self.progress.message = str(e)
            self.progress.error = str(e)
            self.progress.completed_at = datetime.now().isoformat()
            return {"success": False, "error": str(e)}

    async def _run_lora_training(
        self,
        export_result: dict,
        epochs: int,
        model_name: str,
        base_model: Optional[str],
        progress_callback: Optional[Callable]
    ) -> dict:
        """Run the actual LoRA training loop."""
        import torch
        import torch.nn.functional as F
        from transformers import AutoModel, AutoProcessor

        try:
            from peft import LoraConfig, get_peft_model, TaskType
        except ImportError:
            raise ImportError("peft library required for LoRA training. Install with: pip install peft")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            logging.warning("CUDA not available - training will be very slow")

        self.progress.status = TrainingStatus.TRAINING
        self.progress.message = "Loading base model..."
        if progress_callback:
            await progress_callback(self.progress)

        # Load processor and model
        processor = AutoProcessor.from_pretrained(self.HF_MODEL_ID, trust_remote_code=True)

        # Load model for training (need gradients, so no torch.no_grad)
        model = AutoModel.from_pretrained(
            self.HF_MODEL_ID,
            trust_remote_code=True,
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
        )

        # Configure LoRA
        # Target the attention layers in the decoder for text generation
        lora_config = LoraConfig(
            r=16,  # LoRA rank
            lora_alpha=32,  # LoRA alpha scaling
            target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],  # Attention layers
            lora_dropout=0.05,
            bias="none",
            task_type=TaskType.CAUSAL_LM,
        )

        self.progress.message = "Applying LoRA adapters..."
        if progress_callback:
            await progress_callback(self.progress)

        # Apply LoRA
        model = get_peft_model(model, lora_config)
        model.to(device)
        model.train()

        # Print trainable parameters
        trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
        total_params = sum(p.numel() for p in model.parameters())
        logging.info(f"LoRA trainable params: {trainable_params:,} / {total_params:,} ({100*trainable_params/total_params:.2f}%)")

        # Load training data - split into train and validation (90/10)
        manifest_path = Path(export_result["training_dir"]) / "manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            all_items = json.load(f)

        # Create train/val split
        import random
        random.shuffle(all_items)
        val_size = max(1, len(all_items) // 10)
        val_items = all_items[:val_size]
        training_items = all_items[val_size:]
        logging.info(f"Training items: {len(training_items)}, Validation items: {len(val_items)}")

        # Simple optimizer for LoRA
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)

        # Training loop
        self.progress.message = "Training..."
        epoch_start_time = time.time()

        for epoch in range(epochs):
            if self._cancel_requested:
                logging.info("Training cancelled by user")
                self.progress.status = TrainingStatus.CANCELLED
                self.progress.message = "Training cancelled"
                self.progress.completed_at = datetime.now().isoformat()
                return {"success": False, "error": "Cancelled by user"}

            self.progress.epoch = epoch + 1
            epoch_loss = 0.0
            epoch_correct = 0
            epoch_total = 0
            num_batches = 0

            model.train()
            for item in training_items:
                if self._cancel_requested:
                    break

                try:
                    # Load and process image
                    image = Image.open(item["image_path"]).convert("RGB")

                    # Create input with task prompt
                    task_prompt = "</s><s><predict_bbox><predict_classes><output_markdown>"
                    inputs = processor(
                        images=[image],
                        text=task_prompt,
                        return_tensors="pt",
                        add_special_tokens=False
                    )
                    inputs = {k: v.to(device) if hasattr(v, 'to') else v for k, v in inputs.items()}

                    # Create target labels from ground truth
                    target_text = item["ground_truth"]
                    target_tokens = processor.tokenizer(
                        target_text,
                        return_tensors="pt",
                        padding=True,
                        truncation=True,
                        max_length=2048
                    )
                    labels = target_tokens["input_ids"].to(device)

                    # Forward pass - try getting loss from model first
                    outputs = model(**inputs, labels=labels)

                    # Check if model returned loss, otherwise compute manually
                    if hasattr(outputs, 'loss') and outputs.loss is not None:
                        loss = outputs.loss
                    elif hasattr(outputs, 'logits'):
                        # Manual cross-entropy loss computation
                        logits = outputs.logits
                        # Shift for causal LM: predict next token
                        shift_logits = logits[..., :-1, :].contiguous()
                        # Expand labels to match logits sequence length
                        if labels.size(1) < shift_logits.size(1):
                            # Pad labels with -100 (ignore index)
                            pad_len = shift_logits.size(1) - labels.size(1)
                            labels = F.pad(labels, (0, pad_len), value=-100)
                        shift_labels = labels[..., :shift_logits.size(1)].contiguous()
                        # Compute loss
                        loss = F.cross_entropy(
                            shift_logits.view(-1, shift_logits.size(-1)),
                            shift_labels.view(-1),
                            ignore_index=-100
                        )
                        # Compute token-level accuracy for training
                        preds = shift_logits.argmax(dim=-1)
                        mask = shift_labels != -100
                        epoch_correct += (preds[mask] == shift_labels[mask]).sum().item()
                        epoch_total += mask.sum().item()
                    else:
                        logging.warning("Model output has no loss or logits - skipping")
                        continue

                    # Backward pass
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()

                    epoch_loss += loss.item()
                    num_batches += 1

                except Exception as e:
                    logging.warning(f"Error processing training item: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

            # Calculate training metrics
            avg_loss = epoch_loss / max(1, num_batches)
            train_accuracy = epoch_correct / max(1, epoch_total)
            self.progress.loss = avg_loss
            self.progress.accuracy = train_accuracy

            # Validation phase
            val_loss = 0.0
            val_correct = 0
            val_total = 0
            val_batches = 0

            model.eval()
            with torch.no_grad():
                for item in val_items:
                    try:
                        image = Image.open(item["image_path"]).convert("RGB")
                        task_prompt = "</s><s><predict_bbox><predict_classes><output_markdown>"
                        inputs = processor(
                            images=[image],
                            text=task_prompt,
                            return_tensors="pt",
                            add_special_tokens=False
                        )
                        inputs = {k: v.to(device) if hasattr(v, 'to') else v for k, v in inputs.items()}

                        target_text = item["ground_truth"]
                        target_tokens = processor.tokenizer(
                            target_text,
                            return_tensors="pt",
                            padding=True,
                            truncation=True,
                            max_length=2048
                        )
                        labels = target_tokens["input_ids"].to(device)

                        outputs = model(**inputs, labels=labels)

                        if hasattr(outputs, 'loss') and outputs.loss is not None:
                            val_loss += outputs.loss.item()
                        elif hasattr(outputs, 'logits'):
                            logits = outputs.logits
                            shift_logits = logits[..., :-1, :].contiguous()
                            if labels.size(1) < shift_logits.size(1):
                                pad_len = shift_logits.size(1) - labels.size(1)
                                labels = F.pad(labels, (0, pad_len), value=-100)
                            shift_labels = labels[..., :shift_logits.size(1)].contiguous()
                            loss = F.cross_entropy(
                                shift_logits.view(-1, shift_logits.size(-1)),
                                shift_labels.view(-1),
                                ignore_index=-100
                            )
                            val_loss += loss.item()
                            # Compute accuracy
                            preds = shift_logits.argmax(dim=-1)
                            mask = shift_labels != -100
                            val_correct += (preds[mask] == shift_labels[mask]).sum().item()
                            val_total += mask.sum().item()

                        val_batches += 1
                    except Exception as e:
                        logging.warning(f"Error in validation: {e}")
                        continue

            avg_val_loss = val_loss / max(1, val_batches)
            val_accuracy = val_correct / max(1, val_total)
            self.progress.val_accuracy = val_accuracy

            # Estimate ETA
            elapsed = time.time() - epoch_start_time
            avg_epoch_time = elapsed / (epoch + 1)
            remaining_epochs = epochs - (epoch + 1)
            self.progress.eta_seconds = int(avg_epoch_time * remaining_epochs)

            # Record epoch
            self.progress.epoch_history.append({
                "epoch": epoch + 1,
                "loss": avg_loss,
                "val_loss": avg_val_loss,
                "accuracy": train_accuracy,
                "val_accuracy": val_accuracy,
            })

            # Check for improvement (using validation loss)
            if avg_val_loss < self.progress.best_loss:
                self.progress.best_loss = avg_val_loss
                self.progress.best_accuracy = val_accuracy
                self.progress.no_improve_count = 0
            else:
                self.progress.no_improve_count += 1

            self.progress.message = f"Epoch {epoch + 1}/{epochs} - Loss: {avg_loss:.4f}, Val Loss: {avg_val_loss:.4f}, Acc: {train_accuracy:.1%}, Val Acc: {val_accuracy:.1%}"
            logging.info(f"Epoch {epoch + 1}/{epochs} - Loss: {avg_loss:.4f}, Val Loss: {avg_val_loss:.4f}, Train Acc: {train_accuracy:.1%}, Val Acc: {val_accuracy:.1%}")

            if progress_callback:
                await progress_callback(self.progress)

            # Early stopping
            if self.progress.no_improve_count >= self.PATIENCE:
                logging.info(f"Early stopping: no improvement for {self.PATIENCE} epochs")
                self.progress.early_stopped = True
                break

            # Allow other tasks to run
            await asyncio.sleep(0.1)

        # Save LoRA adapter
        output_path = Path(self.LORA_ADAPTERS_DIR) / model_name
        model.save_pretrained(str(output_path))
        logging.info(f"Saved LoRA adapter to {output_path}")

        # Register the adapter
        self._register_adapter(str(output_path), model_name, epochs)

        self.progress.status = TrainingStatus.COMPLETED
        self.progress.message = f"Training completed! Adapter saved to {output_path}"
        self.progress.completed_at = datetime.now().isoformat()

        return {
            "success": True,
            "adapter_path": str(output_path),
            "model_name": model_name,
            "final_loss": self.progress.loss
        }

    def _register_adapter(self, adapter_path: str, model_name: str, epochs: int):
        """Register a trained LoRA adapter in the registry."""
        registry_path = Path(self.LORA_ADAPTERS_DIR) / "registry.json"

        registry = []
        if registry_path.exists():
            with open(registry_path, "r") as f:
                registry = json.load(f)

        registry.append({
            "name": model_name,
            "path": adapter_path,
            "created": datetime.now().isoformat(),
            "epochs": epochs,
            "best_loss": self.progress.best_loss
        })

        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)

    def cancel_training(self):
        """Cancel ongoing training."""
        logging.info("=== Cancelling Nemotron training ===")
        self._cancel_requested = True

    def get_adapters(self) -> List[dict]:
        """List available LoRA adapters."""
        adapters = []
        adapters_dir = Path(self.LORA_ADAPTERS_DIR)

        registry_path = adapters_dir / "registry.json"
        if registry_path.exists():
            with open(registry_path, "r") as f:
                adapters = json.load(f)

        return sorted(adapters, key=lambda x: x.get("created", ""), reverse=True)

    def get_models(self) -> List[dict]:
        """List available LoRA adapters (alias for get_adapters for API compatibility)."""
        return self.get_adapters()

    def get_active_model_info(self) -> dict:
        """Get information about the currently active LoRA adapter."""
        active_file = Path(self.LORA_ADAPTERS_DIR) / "active_adapter.json"
        if active_file.exists():
            with open(active_file, "r") as f:
                return json.load(f)
        return {
            "name": "base",
            "type": "base_model",
            "description": "Using base Nemotron-Parse model without fine-tuning"
        }

    def activate_model(self, adapter_name: str) -> bool:
        """Set a LoRA adapter as active for inference."""
        if adapter_name == "base":
            # Special case: revert to base model
            active_file = Path(self.LORA_ADAPTERS_DIR) / "active_adapter.json"
            if active_file.exists():
                active_file.unlink()
            return True

        # Check if adapter exists
        adapters = self.get_adapters()
        adapter = next((a for a in adapters if a["name"] == adapter_name), None)
        if not adapter:
            return False

        # Save as active
        active_file = Path(self.LORA_ADAPTERS_DIR) / "active_adapter.json"
        with open(active_file, "w") as f:
            json.dump({
                "name": adapter_name,
                "path": adapter["path"],
                "activated_at": datetime.now().isoformat()
            }, f, indent=2)

        logging.info(f"Activated LoRA adapter: {adapter_name}")
        return True

    def load_adapter(self, adapter_name: str):
        """Load a LoRA adapter for inference."""
        adapter_path = Path(self.LORA_ADAPTERS_DIR) / adapter_name
        if not adapter_path.exists():
            raise ValueError(f"Adapter not found: {adapter_name}")

        import torch
        from transformers import AutoModel, AutoProcessor
        from peft import PeftModel

        processor = AutoProcessor.from_pretrained(self.HF_MODEL_ID, trust_remote_code=True)

        base_model = AutoModel.from_pretrained(
            self.HF_MODEL_ID,
            trust_remote_code=True,
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
        )

        model = PeftModel.from_pretrained(base_model, str(adapter_path))
        model.eval()

        return model, processor


# Global instance
nemotron_training_service = NemotronTrainingService()
