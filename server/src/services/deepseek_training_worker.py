"""
DeepSeek-OCR LoRA training worker.

Run in its own process by deepseek_training_service (`python deepseek_training_worker.py job.json`):
Unsloth patches transformers globally on import, which must not leak into the server, and
a separate process gives all GPU memory back when it ends.

Talks to the parent through stdout: every line starting with "@@" is a JSON event
(status, step, epoch, done, error). Cancelling: the parent creates `cancel_file`.

The input is built exactly like DeepSeek-OCR's own `infer()` (base_size 1024, image_size 640,
crop_mode) with the prompt "<image>\\nFree OCR.", which is what Ollama is sent when BEn uses
a deepseek-ocr model. The loss is computed on the answer only.
"""
import json
import math
import os
import random
import sys
import time

os.environ.setdefault("WANDB_DISABLED", "true")  # a broken wandb install must not stop training
os.environ.setdefault("UNSLOTH_WARN_UNINITIALIZED", "0")

PROMPT_TAIL = "\nFree OCR."
IMAGE_TOKEN_ID = 128815
BOS_ID = 0
BASE_SIZE, IMAGE_SIZE, PATCH_SIZE, DOWNSAMPLE = 1024, 640, 16, 4
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def emit(event: str, **data):
    print("@@" + json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


class Batcher:
    """Builds DeepSeek-OCR model inputs for one image and its transcription."""

    def __init__(self, model_module, tokenizer):
        import torch
        self.torch = torch
        self.mod = model_module
        self.tokenizer = tokenizer
        self.transform = model_module.BasicImageTransform(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5), normalize=True)

    def build(self, image, answer: str):
        torch, mod = self.torch, self.mod
        from PIL import ImageOps

        ids, mask = [BOS_ID], [False]
        if image.size[0] <= IMAGE_SIZE and image.size[1] <= IMAGE_SIZE:
            crops, (w, h) = [], (1, 1)
        else:
            crops, (w, h) = mod.dynamic_preprocess(image)
        fill = tuple(int(x * 255) for x in self.transform.mean)
        global_view = ImageOps.pad(image, (BASE_SIZE, BASE_SIZE), color=fill)
        images_ori = self.transform(global_view).to(torch.bfloat16).unsqueeze(0)
        if w > 1 or h > 1:
            images_crop = torch.stack([self.transform(c).to(torch.bfloat16) for c in crops])
        else:
            images_crop = torch.zeros((1, 3, BASE_SIZE, BASE_SIZE), dtype=torch.bfloat16)

        nq = math.ceil((IMAGE_SIZE // PATCH_SIZE) / DOWNSAMPLE)
        nq_base = math.ceil((BASE_SIZE // PATCH_SIZE) / DOWNSAMPLE)
        image_tokens = ([IMAGE_TOKEN_ID] * nq_base + [IMAGE_TOKEN_ID]) * nq_base + [IMAGE_TOKEN_ID]
        if w > 1 or h > 1:
            image_tokens += ([IMAGE_TOKEN_ID] * (nq * w) + [IMAGE_TOKEN_ID]) * (nq * h)
        ids += image_tokens
        mask += [True] * len(image_tokens)

        tail = mod.text_encode(self.tokenizer, PROMPT_TAIL, bos=False, eos=False)
        ids += tail
        mask += [False] * len(tail)
        prompt_len = len(ids)
        answer_ids = mod.text_encode(self.tokenizer, answer, bos=False, eos=True)
        ids += answer_ids
        mask += [False] * len(answer_ids)

        input_ids = torch.tensor([ids])
        labels = input_ids.clone()
        labels[:, :prompt_len] = -100
        return {
            "input_ids": input_ids,
            "labels": labels,
            "images": [(images_crop, images_ori)],
            "images_seq_mask": torch.tensor([mask]),
            "images_spatial_crop": torch.tensor([[w, h]], dtype=torch.long),
        }

    @staticmethod
    def to_device(batch, device):
        return {
            "input_ids": batch["input_ids"].to(device),
            "labels": batch["labels"].to(device),
            "images": [(c.to(device), o.to(device)) for c, o in batch["images"]],
            "images_seq_mask": batch["images_seq_mask"].to(device),
            "images_spatial_crop": batch["images_spatial_crop"],
        }


def main(job_path: str):
    job = json.load(open(job_path, encoding="utf-8"))
    cancel_file = job["cancel_file"]

    def cancelled():
        return os.path.exists(cancel_file)

    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("DeepSeek-OCR training needs a CUDA GPU")
    device = "cuda"

    vram_gb = torch.cuda.get_device_properties(0).total_memory / 2 ** 30
    load_in_4bit = job.get("load_in_4bit")
    if load_in_4bit is None:
        load_in_4bit = vram_gb < 12
    max_tokens = job.get("max_tokens") or (2560 if vram_gb < 12 else 6144)

    emit("status", message=f"Loading DeepSeek-OCR ({'4-bit' if load_in_4bit else '16-bit'}, "
                           f"GPU {vram_gb:.0f} GB)...")
    import unsloth  # noqa: F401  (before transformers)
    from unsloth import FastVisionModel
    from transformers import AutoModel
    from PIL import Image

    model, tokenizer = FastVisionModel.from_pretrained(
        job["base_model_dir"], load_in_4bit=load_in_4bit, auto_model=AutoModel,
        trust_remote_code=True, unsloth_force_compile=True, use_gradient_checkpointing="unsloth",
    )
    model = FastVisionModel.get_peft_model(
        model, target_modules=TARGET_MODULES, r=16, lora_alpha=16, lora_dropout=0,
        bias="none", random_state=3407, use_rslora=False,
    )
    FastVisionModel.for_training(model)
    batcher = Batcher(sys.modules[model.get_base_model().__class__.__module__], tokenizer)

    items = json.load(open(job["manifest"], encoding="utf-8"))
    random.Random(3407).shuffle(items)
    val_size = min(50, max(1, len(items) // 10))
    val_items, train_items = items[:val_size], items[val_size:]

    def prepare(item):
        image = Image.open(item["image_path"]).convert("RGB")
        batch = batcher.build(image, item["ground_truth"])
        if batch["input_ids"].size(1) > max_tokens:
            return None
        return batch

    def run(batch, train: bool):
        batch = Batcher.to_device(batch, device)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            out = model(**batch)
        labels = batch["labels"][:, 1:]
        preds = out.logits[:, :-1, :].argmax(dim=-1)
        m = labels != -100
        correct, total = (preds[m] == labels[m]).sum().item(), m.sum().item()
        return out.loss, correct, total

    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=2e-4)
    epochs, patience = job["epochs"], job["patience"]
    best_loss, best_acc, no_improve, history = float("inf"), 0.0, 0, []
    skipped = set()
    start = time.time()
    steps_done, steps_total = 0, epochs * len(train_items)

    emit("status", message=f"Training on {len(train_items)} pages, validating on {len(val_items)}")
    for epoch in range(1, epochs + 1):
        model.train()
        loss_sum = correct_sum = total_sum = n = 0
        for step, item in enumerate(train_items, 1):
            if cancelled():
                emit("cancelled")
                return
            steps_done += 1
            torch.cuda.empty_cache()  # Windows: otherwise the reservation spills into RAM and OOMs
            try:
                batch = prepare(item)
                if batch is None:
                    skipped.add(item.get("text_id"))
                    continue
                loss, correct, total = run(batch, True)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            except torch.OutOfMemoryError:
                optimizer.zero_grad()
                skipped.add(item.get("text_id"))
                emit("warning", message=f"Out of GPU memory on text {item.get('text_id')}; skipped")
                continue
            loss_sum += loss.item()
            correct_sum += correct
            total_sum += total
            n += 1
            per_step = (time.time() - start) / steps_done
            emit("step", epoch=epoch, step=step, total_steps=len(train_items),
                 loss=loss_sum / n, eta_seconds=int(per_step * (steps_total - steps_done)))

        if n == 0:
            raise RuntimeError("No training page could be processed (all too long or out of memory)")

        emit("status", message=f"Epoch {epoch}/{epochs}: validating on {len(val_items)} pages")
        model.eval()
        v_loss = v_correct = v_total = v_n = 0
        with torch.no_grad():
            for item in val_items:
                if cancelled():
                    emit("cancelled")
                    return
                torch.cuda.empty_cache()
                try:
                    batch = prepare(item)
                    if batch is None:
                        continue
                    loss, correct, total = run(batch, False)
                except torch.OutOfMemoryError:
                    continue
                v_loss += loss.item()
                v_correct += correct
                v_total += total
                v_n += 1
        val_loss = v_loss / max(1, v_n)
        val_acc = v_correct / max(1, v_total)
        entry = {"epoch": epoch, "loss": loss_sum / n, "accuracy": correct_sum / max(1, total_sum),
                 "val_loss": val_loss, "val_accuracy": val_acc}
        history.append(entry)

        improved = val_loss < best_loss
        if improved:
            best_loss, best_acc, no_improve = val_loss, val_acc, 0
            model.save_pretrained(job["output_dir"])  # keep the best epoch
            tokenizer.save_pretrained(job["output_dir"])
        else:
            no_improve += 1
        emit("epoch", **entry, best_loss=best_loss, best_accuracy=best_acc,
             no_improve_count=no_improve, skipped=len(skipped))

        if no_improve >= patience:
            emit("status", message=f"Early stopping: no improvement for {patience} epochs")
            break

    emit("done", best_loss=best_loss, best_accuracy=best_acc, epochs_run=len(history),
         skipped=len(skipped), history=history, load_in_4bit=load_in_4bit, max_tokens=max_tokens)


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as e:  # reported to the parent, which marks the run as failed
        import traceback
        traceback.print_exc()
        emit("error", message=str(e))
        sys.exit(1)
