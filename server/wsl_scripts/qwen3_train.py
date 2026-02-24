#!/usr/bin/env python3
"""
Qwen3-VL Training Script for WSL

Fine-tunes Qwen3-VL on dictionary OCR data using Unsloth + LoRA.
Optimized for 8GB GPU with 4-bit quantization.

Training data format (JSONL):
{"image": "path/to/image.png", "text": "**headword** *akkadian* translation..."}

Usage:
    python3 qwen3_train.py --data_path /path/to/training.jsonl --output_dir ./output
"""

import argparse
import json
import os
from pathlib import Path


def setup_environment():
    """Set up environment for training."""
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"


def load_training_data(data_path: str) -> list:
    """Load training data from JSONL file."""
    data = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def train(
    model_size: str = "4b",
    data_path: str = None,
    output_dir: str = "./qwen3_finetuned",
    epochs: int = 3,
    batch_size: int = 1,
    learning_rate: float = 2e-4,
    lora_r: int = 16,
    lora_alpha: int = 16,
    max_samples: int = None,
):
    """
    Fine-tune Qwen3-VL with LoRA.

    Args:
        model_size: "2b", "4b", or "8b"
        data_path: Path to training data (JSONL)
        output_dir: Where to save the fine-tuned model
        epochs: Number of training epochs
        batch_size: Batch size (keep at 1 for 8GB GPU)
        learning_rate: Learning rate
        lora_r: LoRA rank
        lora_alpha: LoRA alpha
        max_samples: Limit number of samples (for testing)
    """
    setup_environment()

    # Model IDs
    model_ids = {
        "2b": "Qwen/Qwen3-VL-2B",
        "4b": "Qwen/Qwen3-VL-4B",
        "8b": "Qwen/Qwen3-VL-8B",
    }
    model_id = model_ids.get(model_size, model_ids["4b"])

    print(f"Loading model: {model_id}")

    try:
        from unsloth import FastVisionModel
        import torch

        # Load model with 4-bit quantization
        model, tokenizer = FastVisionModel.from_pretrained(
            model_id,
            load_in_4bit=True,
            use_gradient_checkpointing="unsloth",
        )

        print("Adding LoRA adapters...")

        # Add LoRA adapters
        model = FastVisionModel.get_peft_model(
            model,
            r=lora_r,
            lora_alpha=lora_alpha,
            target_modules=[
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj",
            ],
            lora_dropout=0.05,
            bias="none",
            use_rslora=True,
        )

        print(f"Loading training data from: {data_path}")

        # Load and prepare dataset
        from datasets import Dataset
        from PIL import Image
        import base64
        from io import BytesIO

        raw_data = load_training_data(data_path)
        if max_samples:
            raw_data = raw_data[:max_samples]

        print(f"Loaded {len(raw_data)} training samples")

        # Prepare dataset
        def prepare_sample(sample):
            """Convert sample to model input format."""
            # Load image
            if "image_base64" in sample:
                image_data = base64.b64decode(sample["image_base64"])
                image = Image.open(BytesIO(image_data)).convert("RGB")
            else:
                image = Image.open(sample["image"]).convert("RGB")

            # Prepare conversation
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": sample.get("prompt", "OCR this image with markdown formatting.")},
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": sample["text"]},
                    ],
                },
            ]

            return {
                "messages": messages,
                "images": [image],
            }

        # Create dataset
        prepared_data = [prepare_sample(s) for s in raw_data]
        dataset = Dataset.from_list(prepared_data)

        print("Starting training...")

        from trl import SFTTrainer, SFTConfig

        # Training config
        training_args = SFTConfig(
            output_dir=output_dir,
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            gradient_accumulation_steps=4,
            learning_rate=learning_rate,
            weight_decay=0.01,
            warmup_ratio=0.1,
            lr_scheduler_type="cosine",
            logging_steps=10,
            save_strategy="epoch",
            fp16=not torch.cuda.is_bf16_supported(),
            bf16=torch.cuda.is_bf16_supported(),
            optim="adamw_8bit",
            seed=42,
            remove_unused_columns=False,
            dataset_text_field="",  # Not used for vision
            dataset_kwargs={"skip_prepare_dataset": True},
        )

        # Trainer
        trainer = SFTTrainer(
            model=model,
            args=training_args,
            train_dataset=dataset,
            tokenizer=tokenizer,
        )

        # Train
        trainer.train()

        # Save model
        print(f"Saving model to: {output_dir}")
        model.save_pretrained(output_dir)
        tokenizer.save_pretrained(output_dir)

        # Also save as merged model for easier loading
        merged_dir = f"{output_dir}_merged"
        print(f"Saving merged model to: {merged_dir}")
        model.save_pretrained_merged(merged_dir, tokenizer, save_method="merged_16bit")

        print("Training complete!")

        return {
            "success": True,
            "output_dir": output_dir,
            "merged_dir": merged_dir,
            "samples": len(raw_data),
            "epochs": epochs,
        }

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def main():
    parser = argparse.ArgumentParser(description="Fine-tune Qwen3-VL on dictionary OCR data")
    parser.add_argument("--model_size", type=str, default="4b", choices=["2b", "4b", "8b"])
    parser.add_argument("--data_path", type=str, required=True, help="Path to training data (JSONL)")
    parser.add_argument("--output_dir", type=str, default="./qwen3_finetuned")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=1)
    parser.add_argument("--learning_rate", type=float, default=2e-4)
    parser.add_argument("--lora_r", type=int, default=16)
    parser.add_argument("--lora_alpha", type=int, default=16)
    parser.add_argument("--max_samples", type=int, default=None, help="Limit samples for testing")

    args = parser.parse_args()

    result = train(
        model_size=args.model_size,
        data_path=args.data_path,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        max_samples=args.max_samples,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
