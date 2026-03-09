"""
Qwen3-VL QLoRA Fine-tuning Service

Handles QLoRA fine-tuning for Qwen3-VL (4B / 8B) on curated OCR data.
Uses 4-bit quantization (NF4) with LoRA for memory-efficient training on consumer GPUs.
Supports multiple output modes: plain text, TEI Lex-0, and TEI EpiDoc XML.
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

from services.training_common import TrainingStatus, TrainingProgress
from services.ocr_prompts import OUTPUT_MODES, PROMPT_PLAIN_TEXT


class QwenTrainingService:
    """Service for QLoRA fine-tuning of Qwen3-VL models."""

    MIN_LINES = 30
    PATIENCE = 3

    BASE_MODELS = {
        "qwen3-vl-2b": {"hf_id": "Qwen/Qwen3-VL-2B-Instruct", "name": "Qwen3-VL 2B"},
        "qwen3-vl-4b": {"hf_id": "Qwen/Qwen3-VL-4B-Instruct", "name": "Qwen3-VL 4B"},
        "qwen3-vl-8b": {"hf_id": "Qwen/Qwen3-VL-8B-Instruct", "name": "Qwen3-VL 8B"},
    }
    DEFAULT_BASE_MODEL = "qwen3-vl-2b"

    def __init__(self):
        storage_path = os.environ.get("STORAGE_PATH", "data")
        self.TRAINING_DATA_DIR = os.path.join(storage_path, "qwen-training")
        self.LORA_ADAPTERS_DIR = os.path.join(storage_path, "qwen_lora_adapters")
        self.TRAINING_HISTORY_FILE = os.path.join(storage_path, "qwen_training_history.json")
        self.progress = TrainingProgress(
            status=TrainingStatus.IDLE,
            epoch=0, total_epochs=10,
            accuracy=0.0, val_accuracy=0.0, loss=0.0,
            eta_seconds=0, message=""
        )
        self._cancel_requested = False
        self._ensure_directories()
        self._training_history = self._load_training_history()

    # ------------------------------------------------------------------ #
    #  Directory & history helpers
    # ------------------------------------------------------------------ #

    def _ensure_directories(self):
        Path(self.TRAINING_DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.LORA_ADAPTERS_DIR).mkdir(parents=True, exist_ok=True)

    def _load_training_history(self) -> dict:
        try:
            if os.path.exists(self.TRAINING_HISTORY_FILE):
                with open(self.TRAINING_HISTORY_FILE, "r") as f:
                    return json.load(f)
        except Exception as e:
            logging.warning(f"Could not load Qwen training history: {e}")
        return {
            "last_training_timestamp": None,
            "previous_lines": 0,
            "trained_text_ids": []
        }

    def _save_training_history(self, trained_lines: int, trained_text_ids: List[int]):
        self._training_history = {
            "last_training_timestamp": datetime.now().isoformat(),
            "previous_lines": trained_lines,
            "trained_text_ids": trained_text_ids
        }
        try:
            with open(self.TRAINING_HISTORY_FILE, "w") as f:
                json.dump(self._training_history, f, indent=2)
        except Exception as e:
            logging.error(f"Could not save Qwen training history: {e}")

    # ------------------------------------------------------------------ #
    #  Training statistics
    # ------------------------------------------------------------------ #

    def get_training_stats(self, texts_handler, dataset_id: int = None, dataset_ids: list = None) -> dict:
        curated_stats = texts_handler.get_curated_training_stats(target="vlm", dataset_id=dataset_id, dataset_ids=dataset_ids)
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

    # ------------------------------------------------------------------ #
    #  Output modes & base models
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_output_modes() -> Dict[str, str]:
        return {
            "plain": "Plain text transcription (line by line)",
            "tei_lex0": "TEI Lex-0 XML for dictionary entries",
            "tei_epidoc": "TEI EpiDoc XML for cuneiform texts",
        }

    @classmethod
    def get_base_models(cls) -> List[dict]:
        return [
            {"id": key, "name": info["name"], "hf_id": info["hf_id"]}
            for key, info in cls.BASE_MODELS.items()
        ]

    # ------------------------------------------------------------------ #
    #  Export training data
    # ------------------------------------------------------------------ #

    def export_training_data(self, texts_handler, output_mode: str = "plain", dataset_id: int = None, dataset_ids: list = None) -> dict:
        logging.info(f"Exporting training data for Qwen fine-tuning (mode: {output_mode}, dataset_ids={dataset_ids or dataset_id})...")

        training_dir = Path(self.TRAINING_DATA_DIR)
        if training_dir.exists():
            for f in training_dir.glob("*"):
                if f.is_file():
                    f.unlink()

        exported_items = []
        exported_text_ids = []

        curated_data = texts_handler.get_curated_training_data_for("vlm", dataset_id=dataset_id, dataset_ids=dataset_ids)

        for text_data in curated_data:
            text_id = text_data["text_id"]
            image_path = text_data["image_path"]
            lines = text_data["lines"]
            boxes = text_data["boxes"]

            if not os.path.exists(image_path):
                logging.warning(f"Image not found: {image_path}")
                continue

            try:
                img_filename = f"text{text_id}.png"
                dst_path = training_dir / img_filename
                shutil.copy(image_path, dst_path)

                item = {
                    "image_path": str(dst_path),
                    "text_id": text_id,
                    "lines": lines,
                    "boxes": boxes,
                    "ground_truth": self._format_ground_truth(lines, boxes, output_mode),
                }
                exported_items.append(item)
                exported_text_ids.append(text_id)
            except Exception as e:
                logging.error(f"Error processing text {text_id}: {e}")

        manifest_path = training_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(exported_items, f, indent=2, ensure_ascii=False)

        total_lines = sum(len(item["lines"]) for item in exported_items)
        logging.info(f"Exported {total_lines} lines from {len(exported_items)} texts")

        return {
            "exported_lines": total_lines,
            "exported_texts": len(exported_items),
            "exported_text_ids": exported_text_ids,
            "training_dir": str(training_dir),
        }

    def _format_ground_truth(self, lines: List[str], boxes: List[dict], output_mode: str) -> str:
        cleaned = [line.strip() for line in lines if line.strip()]

        if output_mode == "tei_lex0":
            entries = []
            for line in cleaned:
                entries.append(
                    f'<entry xml:lang="akk">\n'
                    f'  <form type="lemma"><orth>{line}</orth></form>\n'
                    f'</entry>'
                )
            return '<body>\n' + '\n'.join(entries) + '\n</body>'

        elif output_mode == "tei_epidoc":
            lb_lines = []
            for i, line in enumerate(cleaned, 1):
                lb_lines.append(f'    <lb n="{i}"/>{line}')
            return (
                '<div type="edition" xml:lang="akk">\n'
                '  <ab>\n'
                + '\n'.join(lb_lines) + '\n'
                '  </ab>\n'
                '</div>'
            )

        else:
            return '\n'.join(cleaned)

    # ------------------------------------------------------------------ #
    #  Main training entry point
    # ------------------------------------------------------------------ #

    async def start_training(
        self,
        texts_handler,
        epochs: int = 10,
        model_name: Optional[str] = None,
        base_model: str = None,
        output_mode: str = "plain",
        device: str = "auto",
        patience: int = None,
        progress_callback: Optional[Callable] = None,
        dataset_id: int = None,
        dataset_ids: list = None,
    ) -> dict:
        try:
            if not base_model:
                base_model = self.DEFAULT_BASE_MODEL

            if base_model not in self.BASE_MODELS:
                raise ValueError(f"Unknown base model: {base_model}. Valid: {list(self.BASE_MODELS.keys())}")

            hf_model_id = self.BASE_MODELS[base_model]["hf_id"]
            self._patience = patience if patience is not None else self.PATIENCE
            logging.info(f"=== Starting Qwen QLoRA training: epochs={epochs}, base={base_model}, mode={output_mode} ===")

            self._cancel_requested = False
            self.progress = TrainingProgress(
                status=TrainingStatus.PREPARING,
                epoch=0, total_epochs=epochs,
                accuracy=0.0, val_accuracy=0.0, loss=0.0,
                eta_seconds=0,
                message="Preparing training data...",
                model_name=model_name,
                started_at=datetime.now().isoformat(),
            )

            if progress_callback:
                await progress_callback(self.progress)

            export_result = self.export_training_data(texts_handler, output_mode, dataset_id=dataset_id, dataset_ids=dataset_ids)

            if export_result["exported_lines"] < self.MIN_LINES:
                raise ValueError(
                    f"Not enough training data. Need at least {self.MIN_LINES} lines, "
                    f"got {export_result['exported_lines']}"
                )

            if not model_name:
                model_name = f"qwen_lora_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.progress.model_name = model_name
            self.progress.message = "Loading model and preparing QLoRA..."

            if progress_callback:
                await progress_callback(self.progress)

            result = await self._run_qlora_training(
                export_result, epochs, model_name, base_model, hf_model_id, output_mode, device, progress_callback
            )

            if result["success"]:
                self._save_training_history(
                    trained_lines=export_result["exported_lines"],
                    trained_text_ids=export_result["exported_text_ids"],
                )

            return result

        except Exception as e:
            logging.error(f"=== Qwen training error: {e} ===")
            import traceback
            traceback.print_exc()
            self.progress.status = TrainingStatus.FAILED
            self.progress.message = str(e)
            self.progress.error = str(e)
            self.progress.completed_at = datetime.now().isoformat()
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  QLoRA training loop
    # ------------------------------------------------------------------ #

    async def _run_qlora_training(
        self,
        export_result: dict,
        epochs: int,
        model_name: str,
        base_model: str,
        hf_model_id: str,
        output_mode: str,
        device_choice: str,
        progress_callback: Optional[Callable],
    ) -> dict:
        import torch
        import torch.nn.functional as F
        from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig

        try:
            from peft import LoraConfig, get_peft_model, TaskType, prepare_model_for_kbit_training
        except ImportError:
            raise ImportError(
                "peft library required for QLoRA training. "
                "Install with: pip install peft bitsandbytes"
            )

        # Resolve device
        if device_choice == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        elif device_choice == "cpu":
            device = "cpu"
        else:
            device = f"cuda:{device_choice}"

        if not device.startswith("cuda"):
            logging.warning("CUDA not available — QLoRA training requires a GPU")
            raise RuntimeError("QLoRA training requires a CUDA GPU")

        device_map = {"": int(device.split(":")[-1])} if ":" in device else "auto"

        self.progress.status = TrainingStatus.TRAINING
        self.progress.message = f"Loading {self.BASE_MODELS[base_model]['name']} with 4-bit quantization..."
        if progress_callback:
            await progress_callback(self.progress)

        # Clear GPU cache
        torch.cuda.empty_cache()

        # Load processor (Qwen3-VL uses a processor, not a tokenizer)
        processor = AutoProcessor.from_pretrained(hf_model_id, trust_remote_code=True)

        # 4-bit quantization config
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )

        # Load model
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            hf_model_id,
            trust_remote_code=True,
            quantization_config=bnb_config,
            device_map=device_map,
            torch_dtype=torch.bfloat16,
            attn_implementation="eager",
        )

        # Prepare for k-bit training
        model = prepare_model_for_kbit_training(model)

        # Find target modules
        target_modules = self._find_target_modules(model)
        logging.info(f"LoRA target modules: {target_modules}")

        # LoRA config
        lora_config = LoraConfig(
            r=16,
            lora_alpha=32,
            target_modules=target_modules,
            lora_dropout=0.05,
            bias="none",
            task_type=TaskType.CAUSAL_LM,
        )

        self.progress.message = "Applying LoRA adapters..."
        if progress_callback:
            await progress_callback(self.progress)

        model = get_peft_model(model, lora_config)
        model.train()

        trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
        total_params = sum(p.numel() for p in model.parameters())
        logging.info(
            f"QLoRA trainable params: {trainable_params:,} / {total_params:,} "
            f"({100 * trainable_params / total_params:.2f}%)"
        )

        # Load training data
        manifest_path = Path(export_result["training_dir"]) / "manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            all_items = json.load(f)

        import random
        random.shuffle(all_items)
        val_size = max(1, len(all_items) // 10)
        val_items = all_items[:val_size]
        training_items = all_items[val_size:]
        logging.info(f"Training items: {len(training_items)}, Validation items: {len(val_items)}")

        # Select the prompt for this output mode
        prompt_text = OUTPUT_MODES.get(output_mode, PROMPT_PLAIN_TEXT)

        # Optimizer
        optimizer = torch.optim.AdamW(
            (p for p in model.parameters() if p.requires_grad), lr=2e-4
        )

        # Training loop
        self.progress.message = "Training..."
        epoch_start_time = time.time()

        # Get the tokenizer from the processor for token-level operations
        tokenizer = processor.tokenizer if hasattr(processor, 'tokenizer') else processor

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
                    loss, correct, total = self._train_step(
                        model, tokenizer, item, prompt_text, device
                    )
                    if loss is None:
                        continue

                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()

                    epoch_loss += loss.item()
                    epoch_correct += correct
                    epoch_total += total
                    num_batches += 1

                except Exception as e:
                    logging.warning(f"Error processing training item: {e}")
                    continue

            # Training metrics
            avg_loss = epoch_loss / max(1, num_batches)
            train_accuracy = epoch_correct / max(1, epoch_total)
            self.progress.loss = avg_loss
            self.progress.accuracy = train_accuracy

            # Validation
            val_loss, val_accuracy = self._validate(
                model, tokenizer, val_items, prompt_text, device
            )
            self.progress.val_accuracy = val_accuracy
            self.progress.val_loss = val_loss

            # ETA
            elapsed = time.time() - epoch_start_time
            avg_epoch_time = elapsed / (epoch + 1)
            remaining = epochs - (epoch + 1)
            self.progress.eta_seconds = int(avg_epoch_time * remaining)

            # Epoch history
            self.progress.epoch_history.append({
                "epoch": epoch + 1,
                "loss": avg_loss,
                "val_loss": val_loss,
                "accuracy": train_accuracy,
                "val_accuracy": val_accuracy,
            })

            # Best tracking
            if val_loss < self.progress.best_loss:
                self.progress.best_loss = val_loss
                self.progress.best_accuracy = val_accuracy
                self.progress.no_improve_count = 0
            else:
                self.progress.no_improve_count += 1

            self.progress.message = (
                f"Epoch {epoch + 1}/{epochs} — "
                f"Loss: {avg_loss:.4f}, Val Loss: {val_loss:.4f}, "
                f"Acc: {train_accuracy:.1%}, Val Acc: {val_accuracy:.1%}"
            )
            logging.info(self.progress.message)

            if progress_callback:
                await progress_callback(self.progress)

            # Early stopping
            if self.progress.no_improve_count >= self._patience:
                logging.info(f"Early stopping: no improvement for {self._patience} epochs")
                self.progress.early_stopped = True
                break

            await asyncio.sleep(0.1)

        # Save adapter
        output_path = Path(self.LORA_ADAPTERS_DIR) / model_name
        model.save_pretrained(str(output_path))
        logging.info(f"Saved QLoRA adapter to {output_path}")

        self._register_adapter(str(output_path), model_name, epochs, base_model, output_mode)

        self.progress.status = TrainingStatus.COMPLETED
        self.progress.message = f"Training completed! Adapter saved as {model_name}"
        self.progress.completed_at = datetime.now().isoformat()

        # Free GPU memory
        del model, tokenizer, processor, optimizer
        torch.cuda.empty_cache()

        return {
            "success": True,
            "adapter_path": str(output_path),
            "model_name": model_name,
            "base_model": base_model,
            "final_loss": self.progress.loss,
            "output_mode": output_mode,
        }

    # ------------------------------------------------------------------ #
    #  Train / validate helpers
    # ------------------------------------------------------------------ #

    def _train_step(self, model, tokenizer, item, prompt_text, device):
        """Single training step. Returns (loss, correct_tokens, total_tokens) or (None, 0, 0)."""
        import torch
        import torch.nn.functional as F

        full_prompt = f"<image>\n{prompt_text}"
        target_text = item["ground_truth"]

        input_text = full_prompt + "\n" + target_text
        tokens = tokenizer(
            input_text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=2048,
        )
        input_ids = tokens["input_ids"].to(device)
        attention_mask = tokens["attention_mask"].to(device)

        # Create labels: mask the prompt portion with -100
        prompt_tokens = tokenizer(
            full_prompt + "\n",
            return_tensors="pt",
            truncation=True,
            max_length=2048,
        )
        prompt_len = prompt_tokens["input_ids"].size(1)

        labels = input_ids.clone()
        labels[:, :prompt_len] = -100

        # Forward pass
        outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)

        if hasattr(outputs, "loss") and outputs.loss is not None:
            loss = outputs.loss
            if hasattr(outputs, "logits"):
                logits = outputs.logits[:, prompt_len - 1:-1, :]
                target_ids = input_ids[:, prompt_len:]
                preds = logits.argmax(dim=-1)
                mask = target_ids != tokenizer.pad_token_id
                correct = (preds[mask] == target_ids[mask]).sum().item()
                total = mask.sum().item()
            else:
                correct, total = 0, 0
            return loss, correct, total

        elif hasattr(outputs, "logits"):
            logits = outputs.logits
            shift_logits = logits[:, :-1, :].contiguous()
            shift_labels = labels[:, 1:].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, shift_logits.size(-1)),
                shift_labels.view(-1),
                ignore_index=-100,
            )
            preds = shift_logits.argmax(dim=-1)
            mask = shift_labels != -100
            correct = (preds[mask] == shift_labels[mask]).sum().item()
            total = mask.sum().item()
            return loss, correct, total

        return None, 0, 0

    def _validate(self, model, tokenizer, val_items, prompt_text, device):
        """Run validation and return (avg_val_loss, val_accuracy)."""
        import torch

        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        val_batches = 0

        with torch.no_grad():
            for item in val_items:
                try:
                    loss, correct, total = self._train_step(
                        model, tokenizer, item, prompt_text, device
                    )
                    if loss is not None:
                        val_loss += loss.item()
                        val_correct += correct
                        val_total += total
                        val_batches += 1
                except Exception as e:
                    logging.warning(f"Error in validation: {e}")

        avg_val_loss = val_loss / max(1, val_batches)
        val_accuracy = val_correct / max(1, val_total)
        return avg_val_loss, val_accuracy

    # ------------------------------------------------------------------ #
    #  Module discovery for LoRA targets
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_target_modules(model) -> List[str]:
        """Inspect model to find linear attention layers for LoRA targeting."""
        import torch.nn as nn

        candidates = {"q_proj", "k_proj", "v_proj", "o_proj",
                       "qkv_proj", "out_proj", "gate_proj", "up_proj", "down_proj"}
        found = set()
        for name, module in model.named_modules():
            if isinstance(module, nn.Linear):
                short = name.split(".")[-1]
                if short in candidates:
                    found.add(short)

        if not found:
            for name, module in model.named_modules():
                if isinstance(module, nn.Linear) and "proj" in name:
                    found.add(name.split(".")[-1])

        if not found:
            found = {"q_proj", "v_proj"}
            logging.warning(f"Could not auto-detect LoRA targets, using fallback: {found}")

        return sorted(found)

    # ------------------------------------------------------------------ #
    #  Adapter management
    # ------------------------------------------------------------------ #

    def _register_adapter(self, adapter_path: str, model_name: str, epochs: int, base_model: str, output_mode: str):
        registry_path = Path(self.LORA_ADAPTERS_DIR) / "registry.json"
        registry = []
        if registry_path.exists():
            with open(registry_path, "r") as f:
                registry = json.load(f)

        # Extract final val_loss from last epoch history entry
        last_val_loss = None
        if self.progress.epoch_history:
            last_val_loss = self.progress.epoch_history[-1].get("val_loss")

        registry.append({
            "name": model_name,
            "path": adapter_path,
            "created": datetime.now().isoformat(),
            "epochs": epochs,
            "base_model": base_model,
            "output_mode": output_mode,
            "best_loss": self.progress.best_loss,
            "best_accuracy": self.progress.best_accuracy,
            "final_accuracy": self.progress.accuracy,
            "final_val_accuracy": self.progress.val_accuracy,
            "final_val_loss": last_val_loss,
        })

        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)

    def cancel_training(self):
        logging.info("=== Cancelling Qwen training ===")
        self._cancel_requested = True

    def get_adapters(self) -> List[dict]:
        registry_path = Path(self.LORA_ADAPTERS_DIR) / "registry.json"
        if registry_path.exists():
            with open(registry_path, "r") as f:
                adapters = json.load(f)
            return sorted(adapters, key=lambda x: x.get("created", ""), reverse=True)
        return []

    def get_models(self) -> List[dict]:
        return self.get_adapters()

    def get_active_model_info(self) -> dict:
        active_file = Path(self.LORA_ADAPTERS_DIR) / "active_adapter.json"
        if active_file.exists():
            with open(active_file, "r") as f:
                return json.load(f)
        return {
            "name": "base",
            "type": "base_model",
            "description": "Using base Qwen3-VL model without fine-tuning",
        }

    def activate_model(self, adapter_name: str) -> bool:
        if adapter_name == "base":
            active_file = Path(self.LORA_ADAPTERS_DIR) / "active_adapter.json"
            if active_file.exists():
                active_file.unlink()
            return True

        adapters = self.get_adapters()
        adapter = next((a for a in adapters if a["name"] == adapter_name), None)
        if not adapter:
            return False

        active_file = Path(self.LORA_ADAPTERS_DIR) / "active_adapter.json"
        with open(active_file, "w") as f:
            json.dump({
                "name": adapter_name,
                "path": adapter["path"],
                "base_model": adapter.get("base_model", self.DEFAULT_BASE_MODEL),
                "output_mode": adapter.get("output_mode", "plain"),
                "activated_at": datetime.now().isoformat(),
            }, f, indent=2)

        logging.info(f"Activated Qwen LoRA adapter: {adapter_name}")
        return True

    def delete_model(self, adapter_name: str) -> bool:
        adapters = self.get_adapters()
        adapter = next((a for a in adapters if a["name"] == adapter_name), None)
        if not adapter:
            return False

        active_info = self.get_active_model_info()
        if active_info.get("name") == adapter_name:
            logging.warning(f"Cannot delete active adapter: {adapter_name}")
            return False

        adapter_path = Path(adapter["path"])
        if adapter_path.exists():
            shutil.rmtree(adapter_path)

        registry_path = Path(self.LORA_ADAPTERS_DIR) / "registry.json"
        updated = [a for a in adapters if a["name"] != adapter_name]
        with open(registry_path, "w") as f:
            json.dump(updated, f, indent=2)

        logging.info(f"Deleted Qwen adapter: {adapter_name}")
        return True


# Global singleton
qwen_training_service = QwenTrainingService()
