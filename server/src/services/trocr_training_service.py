"""
TrOCR Fine-tuning Service

Handles fine-tuning of Microsoft TrOCR (base-handwritten) on curated OCR line data.
TrOCR is a Vision Encoder-Decoder model (ViT encoder + GPT-2 decoder) specifically
designed for line-level OCR. It uses the same Kraken line-image training data
(PNG + .gt.txt pairs).
"""
import asyncio
import json
import logging
import os
import shutil
import time
import glob
import random
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable

from services.training_common import TrainingStatus, TrainingProgress


# ------------------------------------------------------------------ #
#  Text normalization for GPT-2 tokenizer compatibility
# ------------------------------------------------------------------ #
#  GPT-2 tokenizes some transliteration characters as 2-3 byte tokens,
#  making them very hard to learn with limited data. We map the most
#  frequent offenders to single ASCII tokens that don't appear in
#  the ground truth, then reverse the mapping after inference.
#
#  ⸢ (3 tokens, ~1400x) → @     ṣ (2 tokens, ~800x) → %
#  ⸣ (3 tokens, ~1400x) → &     ḫ (2 tokens, ~800x) → ^
#  Š (2 tokens, ~800x)  → ~     ù (2 tokens, ~400x) → _
#  ṭ (2 tokens, ~230x)  → |     ì (2 tokens, ~50x)  → `
#  ʾ (2 tokens, ~100x)  → unused (keep as-is, rare enough)
# ------------------------------------------------------------------ #

_NORMALIZE_MAP = {
    '\u2E22': '@',   # ⸢ half bracket open
    '\u2E23': '&',   # ⸣ half bracket close
    '\u1E63': '%',   # ṣ s-dot-below
    '\u1E2B': '^',   # ḫ h-breve-below
    '\u0160': '~',   # Š capital shin
    '\u00F9': '_',   # ù u-grave
    '\u1E6D': '|',   # ṭ t-dot-below
}
_DENORMALIZE_MAP = {v: k for k, v in _NORMALIZE_MAP.items()}


def normalize_for_trocr(text: str) -> str:
    """Replace multi-byte transliteration chars with single ASCII tokens."""
    for orig, repl in _NORMALIZE_MAP.items():
        text = text.replace(orig, repl)
    return text


def denormalize_from_trocr(text: str) -> str:
    """Reverse the ASCII substitutions back to proper transliteration chars."""
    for repl, orig in _DENORMALIZE_MAP.items():
        text = text.replace(repl, orig)
    return text


class TrOCRTrainingService:
    """Service for fine-tuning TrOCR on line images for Latin-script transliteration OCR."""

    MIN_LINES = 30
    PATIENCE = 5

    BASE_MODELS = {
        "trocr-base-stage1": {
            "hf_id": "microsoft/trocr-base-stage1",
            "name": "TrOCR Base Stage1 (recommended)",
            "params": "~334M",
        },
        "trocr-small-stage1": {
            "hf_id": "microsoft/trocr-small-stage1",
            "name": "TrOCR Small Stage1",
            "params": "~62M",
        },
        "trocr-base-handwritten": {
            "hf_id": "microsoft/trocr-base-handwritten",
            "name": "TrOCR Base Handwritten",
            "params": "~334M",
        },
        "trocr-small-handwritten": {
            "hf_id": "microsoft/trocr-small-handwritten",
            "name": "TrOCR Small Handwritten",
            "params": "~62M",
        },
    }
    DEFAULT_BASE_MODEL = "trocr-base-stage1"

    def __init__(self):
        storage_path = os.environ.get("STORAGE_PATH", "data")
        self.MODELS_DIR = os.path.join(storage_path, "trocr_models")
        self.TRAINING_HISTORY_FILE = os.path.join(storage_path, "trocr_training_history.json")
        self.progress = TrainingProgress(
            status=TrainingStatus.IDLE,
            epoch=0, total_epochs=10,
            accuracy=0.0, val_accuracy=0.0, loss=0.0,
            eta_seconds=0, message=""
        )
        self._cancel_requested = False
        self._ensure_directories()
        self._training_history = self._load_training_history()

    def _ensure_directories(self):
        Path(self.MODELS_DIR).mkdir(parents=True, exist_ok=True)

    def _load_training_history(self) -> dict:
        try:
            if os.path.exists(self.TRAINING_HISTORY_FILE):
                with open(self.TRAINING_HISTORY_FILE, "r") as f:
                    return json.load(f)
        except Exception as e:
            logging.warning(f"Could not load TrOCR training history: {e}")
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
            logging.error(f"Could not save TrOCR training history: {e}")

    # ------------------------------------------------------------------ #
    #  Training statistics
    # ------------------------------------------------------------------ #

    def get_training_stats(self, texts_handler, dataset_id: int = None, dataset_ids: list = None) -> dict:
        curated_stats = texts_handler.get_curated_training_stats(target="kraken", dataset_id=dataset_id, dataset_ids=dataset_ids)
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

    @classmethod
    def get_base_models(cls) -> List[dict]:
        return [
            {"id": key, "name": info["name"], "hf_id": info["hf_id"], "params": info["params"]}
            for key, info in cls.BASE_MODELS.items()
        ]

    # ------------------------------------------------------------------ #
    #  Load line-image training pairs (reuse Kraken data)
    # ------------------------------------------------------------------ #

    def _load_training_pairs(self, kraken_training_service, texts_handler,
                             dataset_id=None, dataset_ids=None) -> dict:
        """
        Use Kraken's export to get line images + ground truth,
        then return a list of (image_path, ground_truth_text) pairs.
        """
        export_result = kraken_training_service.export_training_data(
            texts_handler, dataset_id=dataset_id, dataset_ids=dataset_ids
        )

        training_dir = export_result.get("training_dir")
        pairs = []
        text_ids = set()

        for gt_file in sorted(glob.glob(os.path.join(training_dir, "**", "*.gt.txt"), recursive=True)):
            png_file = gt_file.replace(".gt.txt", ".png")
            if not os.path.exists(png_file):
                continue

            with open(gt_file, "r", encoding="utf-8") as f:
                gt_text = f.read().strip()

            if not gt_text:
                continue

            pairs.append({"image_path": png_file, "ground_truth": gt_text})

            # Extract text ID for history tracking
            name = os.path.basename(gt_file).replace(".gt.txt", "")
            parts = name.split("_line")
            if parts:
                try:
                    text_ids.add(int(parts[0].replace("text", "")))
                except ValueError:
                    pass

        return {
            "pairs": pairs,
            "total_lines": len(pairs),
            "text_ids": sorted(text_ids),
        }

    # ------------------------------------------------------------------ #
    #  Main training entry point
    # ------------------------------------------------------------------ #

    async def start_training(
        self,
        texts_handler,
        kraken_training_service,
        epochs: int = 30,
        model_name: Optional[str] = None,
        base_model: str = None,
        device: str = "auto",
        patience: int = None,
        learning_rate: float = 5e-5,
        freeze_encoder: bool = False,
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
            self._learning_rate = learning_rate
            self._freeze_encoder = freeze_encoder
            logging.info(f"=== Starting TrOCR training: epochs={epochs}, base={base_model}, lr={learning_rate}, freeze_encoder={freeze_encoder} ===")

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

            # Load training pairs from Kraken data
            data = self._load_training_pairs(
                kraken_training_service, texts_handler,
                dataset_id=dataset_id, dataset_ids=dataset_ids
            )

            if data["total_lines"] < self.MIN_LINES:
                raise ValueError(
                    f"Not enough training data. Need at least {self.MIN_LINES} lines, "
                    f"got {data['total_lines']}"
                )

            if not model_name:
                model_name = f"trocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.progress.model_name = model_name
            self.progress.message = f"Loading {self.BASE_MODELS[base_model]['name']}..."

            if progress_callback:
                await progress_callback(self.progress)

            result = await self._run_training(
                data, epochs, model_name, base_model, hf_model_id, device,
                progress_callback, learning_rate=learning_rate, freeze_encoder=freeze_encoder
            )

            if result["success"]:
                self._save_training_history(
                    trained_lines=data["total_lines"],
                    trained_text_ids=data["text_ids"],
                )

            return result

        except Exception as e:
            logging.error(f"=== TrOCR training error: {e} ===")
            import traceback
            traceback.print_exc()
            self.progress.status = TrainingStatus.FAILED
            self.progress.message = str(e)
            self.progress.error = str(e)
            self.progress.completed_at = datetime.now().isoformat()
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Training loop
    # ------------------------------------------------------------------ #

    async def _run_training(
        self,
        data: dict,
        epochs: int,
        model_name: str,
        base_model: str,
        hf_model_id: str,
        device_choice: str,
        progress_callback: Optional[Callable],
        learning_rate: float = 5e-5,
        freeze_encoder: bool = False,
    ) -> dict:
        import torch
        from PIL import Image
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel

        # Resolve device
        if device_choice == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        elif device_choice == "cpu":
            device = "cpu"
        else:
            device = f"cuda:{device_choice}"

        self.progress.status = TrainingStatus.TRAINING
        self.progress.message = f"Loading {self.BASE_MODELS[base_model]['name']}..."
        if progress_callback:
            await progress_callback(self.progress)

        if device.startswith("cuda"):
            torch.cuda.empty_cache()

        # Load model and processor
        processor = TrOCRProcessor.from_pretrained(hf_model_id)
        model = VisionEncoderDecoderModel.from_pretrained(hf_model_id)
        model.to(device)

        # Configure for training
        model.config.decoder_start_token_id = processor.tokenizer.cls_token_id or processor.tokenizer.bos_token_id
        model.config.pad_token_id = processor.tokenizer.pad_token_id
        model.config.eos_token_id = processor.tokenizer.sep_token_id or processor.tokenizer.eos_token_id
        model.config.vocab_size = model.config.decoder.vocab_size
        model.config.max_length = 128

        # Optionally freeze encoder (only train decoder)
        if freeze_encoder:
            for param in model.encoder.parameters():
                param.requires_grad = False
            trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
            total = sum(p.numel() for p in model.parameters())
            logging.info(f"Encoder frozen: training {trainable:,} / {total:,} parameters ({100*trainable/total:.1f}%)")

        # Split data into train/val
        all_pairs = data["pairs"][:]
        random.shuffle(all_pairs)
        val_size = max(1, len(all_pairs) // 10)  # 10% for validation
        val_pairs = all_pairs[:val_size]
        train_pairs = all_pairs[val_size:]

        logging.info(f"Training: {len(train_pairs)} pairs, Validation: {len(val_pairs)} pairs, lr={learning_rate}")

        # Optimizer
        optimizer = torch.optim.AdamW(
            filter(lambda p: p.requires_grad, model.parameters()),
            lr=learning_rate, weight_decay=0.01
        )

        # Training loop
        self.progress.message = "Training..."
        epoch_start_time = time.time()
        best_model_state = None

        for epoch in range(epochs):
            if self._cancel_requested:
                logging.info("TrOCR training cancelled by user")
                self.progress.status = TrainingStatus.CANCELLED
                self.progress.message = "Training cancelled"
                self.progress.completed_at = datetime.now().isoformat()
                return {"success": False, "error": "Cancelled by user"}

            self.progress.epoch = epoch + 1

            # --- Train ---
            model.train()
            epoch_loss = 0.0
            epoch_correct = 0
            epoch_total = 0
            num_batches = 0

            random.shuffle(train_pairs)

            for pair in train_pairs:
                if self._cancel_requested:
                    break

                try:
                    loss, correct, total = self._train_step(
                        model, processor, pair, device
                    )
                    if loss is None:
                        continue

                    optimizer.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()

                    epoch_loss += loss.item()
                    epoch_correct += correct
                    epoch_total += total
                    num_batches += 1

                except Exception as e:
                    logging.warning(f"Error processing training pair: {e}")
                    continue

            # Training metrics
            avg_loss = epoch_loss / max(1, num_batches)
            train_accuracy = epoch_correct / max(1, epoch_total)
            self.progress.loss = avg_loss
            self.progress.accuracy = train_accuracy

            # --- Validate ---
            val_loss, val_accuracy = self._validate(model, processor, val_pairs, device)
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

            # Best tracking (based on val_loss)
            if val_loss < self.progress.best_loss:
                self.progress.best_loss = val_loss
                self.progress.best_accuracy = val_accuracy
                self.progress.no_improve_count = 0
                # Save best model state
                best_model_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            else:
                self.progress.no_improve_count += 1

            self.progress.message = (
                f"Epoch {epoch + 1}/{epochs} — "
                f"Loss: {avg_loss:.4f}, Val Loss: {val_loss:.4f}, "
                f"Char Acc: {val_accuracy:.1%}"
            )
            logging.info(self.progress.message)

            if progress_callback:
                await progress_callback(self.progress)

            # Allow event loop to process
            await asyncio.sleep(0)

            # Early stopping
            if self.progress.no_improve_count >= self._patience:
                logging.info(f"Early stopping: no improvement for {self._patience} epochs")
                self.progress.early_stopped = True
                break

        # Save the best model
        if self._cancel_requested:
            return {"success": False, "error": "Cancelled by user"}

        model_dir = Path(self.MODELS_DIR) / model_name
        model_dir.mkdir(parents=True, exist_ok=True)

        if best_model_state:
            model.load_state_dict(best_model_state)

        model.save_pretrained(str(model_dir))
        processor.save_pretrained(str(model_dir))

        # Register model
        self._register_model(str(model_dir), model_name, epochs, base_model)

        self.progress.status = TrainingStatus.COMPLETED
        self.progress.message = f"Training complete! Best val accuracy: {self.progress.best_accuracy:.1%}"
        self.progress.completed_at = datetime.now().isoformat()

        if progress_callback:
            await progress_callback(self.progress)

        # Clean up GPU memory
        del model
        if device.startswith("cuda"):
            torch.cuda.empty_cache()

        logging.info(f"=== TrOCR training complete: {model_name} ===")
        return {
            "success": True,
            "model_name": model_name,
            "best_accuracy": self.progress.best_accuracy,
            "best_loss": self.progress.best_loss,
            "epochs_trained": self.progress.epoch,
            "early_stopped": self.progress.early_stopped,
        }

    # ------------------------------------------------------------------ #
    #  Image preprocessing
    # ------------------------------------------------------------------ #

    @staticmethod
    def _prepare_image(image, target_size: int = 384):
        """
        Prepare a line image for TrOCR: resize to fit target width while
        preserving aspect ratio, then pad height with white to make it square.

        Without this, TrOCR's default processor squashes 355x34 images to
        384x384, stretching characters ~11x vertically and destroying
        their proportions.
        """
        from PIL import Image as PILImage

        img = image.convert("RGB")
        w, h = img.size

        if w == 0 or h == 0:
            return PILImage.new("RGB", (target_size, target_size), (255, 255, 255))

        # Resize to fit target width, preserve aspect ratio
        scale = target_size / w
        new_w = target_size
        new_h = min(int(h * scale), target_size)

        resized = img.resize((new_w, new_h), PILImage.BILINEAR)

        # Pad height to target_size with white (text at top)
        if new_h < target_size:
            padded = PILImage.new("RGB", (target_size, target_size), (255, 255, 255))
            padded.paste(resized, (0, 0))
            return padded

        return resized

    # ------------------------------------------------------------------ #
    #  Train / validate steps
    # ------------------------------------------------------------------ #

    def _train_step(self, model, processor, pair, device):
        """Process a single training pair: image → text."""
        import torch
        from PIL import Image

        img = self._prepare_image(Image.open(pair["image_path"]))
        gt_text = normalize_for_trocr(pair["ground_truth"])

        # Encode image (processor still normalizes pixel values)
        pixel_values = processor(images=img, return_tensors="pt").pixel_values.to(device)

        # Encode target text (normalized to single-token ASCII)
        labels = processor.tokenizer(
            gt_text,
            return_tensors="pt",
            padding="max_length",
            max_length=128,
            truncation=True,
        ).input_ids.to(device)

        # Replace padding token id with -100 so it's ignored in loss
        labels[labels == processor.tokenizer.pad_token_id] = -100

        # Forward pass
        outputs = model(pixel_values=pixel_values, labels=labels)

        loss = outputs.loss
        if loss is None:
            return None, 0, 0

        # Calculate accuracy
        logits = outputs.logits
        preds = logits.argmax(dim=-1)
        mask = labels != -100
        correct = (preds[:, :mask.shape[1]][mask] == labels[mask]).sum().item()
        total = mask.sum().item()

        return loss, correct, total

    @staticmethod
    def _edit_distance(s1: str, s2: str) -> int:
        """Compute Levenshtein edit distance between two strings."""
        if len(s1) < len(s2):
            return TrOCRTrainingService._edit_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                cost = 0 if c1 == c2 else 1
                curr_row.append(min(
                    curr_row[j] + 1,         # insert
                    prev_row[j + 1] + 1,     # delete
                    prev_row[j] + cost,       # replace
                ))
            prev_row = curr_row
        return prev_row[-1]

    def _validate(self, model, processor, val_pairs, device):
        """Run validation and return (avg_val_loss, val_char_accuracy).

        Uses actual text generation + character-level edit distance
        for a meaningful OCR accuracy metric (instead of BPE token accuracy).
        """
        import torch
        from PIL import Image

        model.eval()
        val_loss = 0.0
        val_batches = 0

        # Compute loss on all validation pairs
        with torch.no_grad():
            for pair in val_pairs:
                try:
                    loss, _, _ = self._train_step(
                        model, processor, pair, device
                    )
                    if loss is not None:
                        val_loss += loss.item()
                        val_batches += 1
                except Exception as e:
                    logging.warning(f"Error in TrOCR validation: {e}")

        avg_val_loss = val_loss / max(1, val_batches)

        # Character-level accuracy via actual generation on a subsample
        # Use vocab filter to match real inference conditions
        gen_kwargs = self._get_generate_kwargs(processor, device)
        sample_size = min(20, len(val_pairs))
        sample_pairs = val_pairs[:sample_size]
        total_chars = 0
        total_errors = 0

        with torch.no_grad():
            for pair in sample_pairs:
                try:
                    img = self._prepare_image(Image.open(pair["image_path"]))
                    gt_text = normalize_for_trocr(pair["ground_truth"])

                    pixel_values = processor(
                        images=img, return_tensors="pt"
                    ).pixel_values.to(device)
                    generated_ids = model.generate(
                        pixel_values, **gen_kwargs
                    )
                    pred_text = processor.batch_decode(
                        generated_ids, skip_special_tokens=True
                    )[0]

                    gt_len = len(gt_text)
                    if gt_len > 0:
                        dist = self._edit_distance(pred_text, gt_text)
                        total_errors += dist
                        total_chars += gt_len
                except Exception as e:
                    logging.warning(f"Error in char accuracy eval: {e}")

        if total_chars > 0:
            char_accuracy = max(0.0, 1.0 - total_errors / total_chars)
        else:
            char_accuracy = 0.0

        return avg_val_loss, char_accuracy

    # ------------------------------------------------------------------ #
    #  Inference
    # ------------------------------------------------------------------ #

    # Characters that appear in transliteration ground truth data.
    # Only GPT-2 tokens composed exclusively of these characters are allowed.
    _ALLOWED_CHARS = set(
        " !#$'()*+,-./"
        "0123456789"
        ":;<=>?[]`{}"
        "ABCDEGHIKLMNPRSTUVZabcdefghijklmnopqrstuvwxyz"
        "ªÀ×àáâäèéêìíîùúû"
        "āēěīıśŠšū"
        "ʾʿ˺"
        "̧̀́̃̄"   # combining diacritics
        "ḫṣṭ"
        "\u2018\u2019…"  # curly quotes, ellipsis
        "₁₂₄₅₆₇₈"       # subscript digits
        "↑⌈⌉⸢⸣"
        "¹"
        "а"               # Cyrillic а (appears in data)
    )

    _allowed_token_ids_cache: dict = {}

    def _build_allowed_token_ids(self, processor) -> list:
        """
        Build a list of GPT-2 token IDs whose decoded text contains only
        valid transliteration characters. Cached per processor identity.
        """
        cache_key = id(processor.tokenizer)
        if cache_key in self._allowed_token_ids_cache:
            return self._allowed_token_ids_cache[cache_key]

        tokenizer = processor.tokenizer
        allowed = []
        vocab = tokenizer.get_vocab()

        # Always allow special tokens
        special_ids = set()
        for attr in ("bos_token_id", "eos_token_id", "pad_token_id",
                     "cls_token_id", "sep_token_id", "unk_token_id"):
            tid = getattr(tokenizer, attr, None)
            if tid is not None:
                special_ids.add(tid)

        for token_str, token_id in vocab.items():
            if token_id in special_ids:
                allowed.append(token_id)
                continue
            # Decode the token to get the actual characters
            try:
                decoded = tokenizer.decode([token_id])
                if decoded and all(c in self._ALLOWED_CHARS for c in decoded):
                    allowed.append(token_id)
            except Exception:
                continue

        allowed = sorted(set(allowed))
        logging.info(
            f"TrOCR vocab filter: {len(allowed)} / {len(vocab)} tokens allowed "
            f"({100 * len(allowed) / len(vocab):.1f}%)"
        )
        self._allowed_token_ids_cache[cache_key] = allowed
        return allowed

    def _load_model(self, model_name: str = None):
        """Load TrOCR model and processor. Returns (processor, model, device).

        If model_name is None, checks for an active fine-tuned model first,
        then falls back to the base model.
        """
        import torch
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel

        # Resolve model: explicit name > active model > base model
        if not model_name:
            active_info = self.get_active_model_info()
            if active_info.get("name") and active_info["name"] != "base":
                model_name = active_info["name"]
                logging.info(f"TrOCR: using active model '{model_name}'")

        if model_name:
            model_dir = Path(self.MODELS_DIR) / model_name
            if not model_dir.exists():
                raise ValueError(f"TrOCR model not found: {model_name}")
            logging.info(f"TrOCR: loading fine-tuned model from {model_dir}")
            processor = TrOCRProcessor.from_pretrained(str(model_dir))
            model = VisionEncoderDecoderModel.from_pretrained(str(model_dir))
        else:
            hf_id = self.BASE_MODELS[self.DEFAULT_BASE_MODEL]["hf_id"]
            logging.info(f"TrOCR: loading base model {hf_id}")
            processor = TrOCRProcessor.from_pretrained(hf_id)
            model = VisionEncoderDecoderModel.from_pretrained(hf_id)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        model.eval()
        return processor, model, device

    # Generation parameters
    _GENERATE_KWARGS = {
        "max_new_tokens": 128,
        "num_beams": 4,
        "repetition_penalty": 1.5,
        "no_repeat_ngram_size": 3,
    }

    def _get_generate_kwargs(self, processor, device):
        """Build generation kwargs including vocabulary constraint."""
        import torch
        from transformers import LogitsProcessor, LogitsProcessorList

        allowed_ids = self._build_allowed_token_ids(processor)
        allowed_set = set(allowed_ids)

        class VocabFilter(LogitsProcessor):
            """Mask logits for tokens outside the transliteration character set."""
            def __call__(self, input_ids, scores):
                mask = torch.full_like(scores, float("-inf"))
                for tid in allowed_set:
                    if tid < scores.shape[-1]:
                        mask[:, tid] = 0.0
                return scores + mask

        kwargs = dict(self._GENERATE_KWARGS)
        kwargs["logits_processor"] = LogitsProcessorList([VocabFilter()])
        return kwargs

    def recognize_line(self, image, model_name: str = None) -> str:
        """
        Run TrOCR inference on a single line image.
        Args:
            image: PIL Image (line image)
            model_name: Which fine-tuned model to use (None = base model)
        Returns:
            Predicted text string
        """
        import torch

        processor, model, device = self._load_model(model_name)
        gen_kwargs = self._get_generate_kwargs(processor, device)

        img = self._prepare_image(image)
        pixel_values = processor(images=img, return_tensors="pt").pixel_values.to(device)

        with torch.no_grad():
            generated_ids = model.generate(pixel_values, **gen_kwargs)

        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

        # Reverse ASCII normalization back to proper transliteration chars
        text = denormalize_from_trocr(text)

        del model
        if device == "cuda":
            torch.cuda.empty_cache()

        return text

    def recognize_lines(self, images: list, model_name: str = None) -> list:
        """
        Run TrOCR inference on multiple line images with a single model load.
        Args:
            images: List of PIL Images (one per line)
            model_name: Which fine-tuned model to use (None = base model)
        Returns:
            List of predicted text strings
        """
        import torch

        if not images:
            return []

        processor, model, device = self._load_model(model_name)
        gen_kwargs = self._get_generate_kwargs(processor, device)

        results = []
        for img in images:
            prepared = self._prepare_image(img)
            pixel_values = processor(images=prepared, return_tensors="pt").pixel_values.to(device)

            with torch.no_grad():
                generated_ids = model.generate(pixel_values, **gen_kwargs)

            text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            results.append(denormalize_from_trocr(text))

        del model
        if device == "cuda":
            torch.cuda.empty_cache()

        return results

    # ------------------------------------------------------------------ #
    #  Model management
    # ------------------------------------------------------------------ #

    def _register_model(self, model_path: str, model_name: str, epochs: int, base_model: str):
        registry_path = Path(self.MODELS_DIR) / "registry.json"
        registry = []
        if registry_path.exists():
            with open(registry_path, "r") as f:
                registry = json.load(f)

        last_val_loss = None
        if self.progress.epoch_history:
            last_val_loss = self.progress.epoch_history[-1].get("val_loss")

        registry.append({
            "name": model_name,
            "path": model_path,
            "created": datetime.now().isoformat(),
            "epochs": epochs,
            "epochs_trained": self.progress.epoch,
            "base_model": base_model,
            "best_loss": self.progress.best_loss if self.progress.best_loss != float('inf') else None,
            "best_accuracy": self.progress.best_accuracy,
            "final_accuracy": self.progress.accuracy,
            "final_val_accuracy": self.progress.val_accuracy,
            "final_val_loss": last_val_loss,
            "early_stopped": self.progress.early_stopped,
        })

        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)

    def cancel_training(self):
        logging.info("=== Cancelling TrOCR training ===")
        self._cancel_requested = True

    def get_models(self) -> List[dict]:
        registry_path = Path(self.MODELS_DIR) / "registry.json"
        if registry_path.exists():
            with open(registry_path, "r") as f:
                models = json.load(f)
            return sorted(models, key=lambda x: x.get("created", ""), reverse=True)
        return []

    def get_active_model_info(self) -> dict:
        active_file = Path(self.MODELS_DIR) / "active_model.json"
        if active_file.exists():
            with open(active_file, "r") as f:
                return json.load(f)
        return {
            "name": "base",
            "type": "base_model",
            "description": "Using base TrOCR model without fine-tuning",
        }

    def activate_model(self, model_name: str) -> bool:
        if model_name == "base":
            active_file = Path(self.MODELS_DIR) / "active_model.json"
            if active_file.exists():
                active_file.unlink()
            return True

        models = self.get_models()
        model = next((m for m in models if m["name"] == model_name), None)
        if not model:
            return False

        active_file = Path(self.MODELS_DIR) / "active_model.json"
        with open(active_file, "w") as f:
            json.dump({
                "name": model_name,
                "path": model["path"],
                "base_model": model.get("base_model", self.DEFAULT_BASE_MODEL),
                "activated_at": datetime.now().isoformat(),
            }, f, indent=2)

        logging.info(f"Activated TrOCR model: {model_name}")
        return True

    def delete_model(self, model_name: str) -> bool:
        models = self.get_models()
        model = next((m for m in models if m["name"] == model_name), None)
        if not model:
            return False

        active_info = self.get_active_model_info()
        if active_info.get("name") == model_name:
            return False  # Can't delete active model

        # Delete model files
        model_dir = Path(model["path"])
        if model_dir.exists():
            shutil.rmtree(str(model_dir))

        # Update registry
        registry = [m for m in models if m["name"] != model_name]
        registry_path = Path(self.MODELS_DIR) / "registry.json"
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)

        logging.info(f"Deleted TrOCR model: {model_name}")
        return True


# Singleton instance
trocr_training_service = TrOCRTrainingService()
