"""
Qwen3-VL Local Service for OCR and Training

This service runs Qwen3-VL-4B locally via WSL for:
- OCR with markdown output (bold/italic detection)
- Fine-tuning with LoRA/Unsloth on custom data

Requires WSL2 with Ubuntu and CUDA support.
"""

import subprocess
import json
import base64
import os
from pathlib import Path
from typing import Optional, Dict, List, Union


class Qwen3VLService:
    """
    Qwen3-VL service that runs in WSL2 for training support.
    Uses Unsloth for efficient LoRA fine-tuning.
    """

    # Model variants
    MODELS = {
        "2b": "Qwen/Qwen3-VL-2B",
        "4b": "Qwen/Qwen3-VL-4B",
        "8b": "Qwen/Qwen3-VL-8B",
    }

    # Default prompts for different dictionary types
    PROMPTS = {
        "ahw": """This is a dictionary entry from AHw (Akkadisches Handwörterbuch).
OCR this image with careful attention to typography:
- The headword at the beginning is in BOLD - use **bold**
- Akkadian words and forms are in ITALIC - use *italic* for ALL of them
- German translations are in regular text
- Apply formatting consistently throughout the ENTIRE text, not just the first line.

Output the complete text with markdown formatting.""",

        "cad": """This is a dictionary entry from CAD (Chicago Assyrian Dictionary).
OCR this image with attention to formatting:
- Headwords are in BOLD - use **bold**
- Akkadian words are in ITALIC - use *italic*
- English translations in regular text
Apply formatting throughout the entire text.

Output the complete text with markdown formatting.""",

        "plain": "OCR this image and output the text exactly as shown.",

        "markdown": "OCR this image. Use **bold** for bold text and *italic* for italic text throughout.",
    }

    def __init__(self, model_size: str = "4b", use_4bit: bool = True):
        """
        Initialize Qwen3-VL service.

        Args:
            model_size: "2b", "4b", or "8b"
            use_4bit: Use 4-bit quantization (recommended for 8GB GPU)
        """
        self.model_size = model_size
        self.model_id = self.MODELS.get(model_size, self.MODELS["4b"])
        self.use_4bit = use_4bit
        self.wsl_script_path = self._get_wsl_script_path()

    def _get_wsl_script_path(self) -> str:
        """Get the path to WSL helper scripts."""
        return "/mnt/c/Users/wende/Documents/GitHub/BEn-app/server/wsl_scripts"

    def _run_wsl_command(self, script: str, args: Dict = None) -> Dict:
        """
        Run a Python script in WSL and return the result.

        Args:
            script: Name of the script to run
            args: Arguments to pass as JSON

        Returns:
            Dict with result or error
        """
        args_json = json.dumps(args or {})

        cmd = [
            "wsl", "-d", "Ubuntu", "--",
            "bash", "-c",
            f"cd {self.wsl_script_path} && python3 {script} '{args_json}'"
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 min timeout for model loading
            )

            if result.returncode != 0:
                return {"error": result.stderr, "success": False}

            return json.loads(result.stdout)

        except subprocess.TimeoutExpired:
            return {"error": "Timeout waiting for WSL", "success": False}
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON response: {result.stdout}", "success": False}
        except Exception as e:
            return {"error": str(e), "success": False}

    def is_available(self) -> bool:
        """Check if WSL and required packages are available."""
        try:
            result = subprocess.run(
                ["wsl", "-d", "Ubuntu", "--", "python3", "-c",
                 "import torch; print(torch.cuda.is_available())"],
                capture_output=True,
                text=True,
                timeout=30
            )
            return "True" in result.stdout
        except Exception:
            return False

    def get_status(self) -> Dict:
        """Get service status and GPU info."""
        try:
            result = subprocess.run(
                ["wsl", "-d", "Ubuntu", "--", "python3", "-c", """
import torch
import json
info = {
    "cuda_available": torch.cuda.is_available(),
    "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "gpu_memory_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1) if torch.cuda.is_available() else None,
}
print(json.dumps(info))
"""],
                capture_output=True,
                text=True,
                timeout=30
            )
            return json.loads(result.stdout)
        except Exception as e:
            return {"error": str(e), "cuda_available": False}

    def ocr_image(
        self,
        image_path: str,
        prompt_type: str = "ahw",
        custom_prompt: Optional[str] = None
    ) -> Dict:
        """
        Perform OCR on an image using Qwen3-VL.

        Args:
            image_path: Path to the image file
            prompt_type: One of "ahw", "cad", "plain", "markdown"
            custom_prompt: Override the default prompt

        Returns:
            Dict with "text" (OCR result) or "error"
        """
        prompt = custom_prompt or self.PROMPTS.get(prompt_type, self.PROMPTS["markdown"])

        # Read and encode image
        with open(image_path, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode()

        args = {
            "model_id": self.model_id,
            "use_4bit": self.use_4bit,
            "image_base64": image_base64,
            "prompt": prompt,
        }

        return self._run_wsl_command("qwen3_ocr.py", args)

    def ocr_from_base64(
        self,
        image_base64: str,
        prompt_type: str = "ahw",
        custom_prompt: Optional[str] = None
    ) -> Dict:
        """
        Perform OCR on a base64-encoded image.

        Args:
            image_base64: Base64-encoded image data
            prompt_type: One of "ahw", "cad", "plain", "markdown"
            custom_prompt: Override the default prompt

        Returns:
            Dict with "text" (OCR result) or "error"
        """
        prompt = custom_prompt or self.PROMPTS.get(prompt_type, self.PROMPTS["markdown"])

        args = {
            "model_id": self.model_id,
            "use_4bit": self.use_4bit,
            "image_base64": image_base64,
            "prompt": prompt,
        }

        return self._run_wsl_command("qwen3_ocr.py", args)


# Standalone test
if __name__ == "__main__":
    service = Qwen3VLService(model_size="4b")

    print("Checking WSL availability...")
    print(f"Available: {service.is_available()}")

    print("\nGetting GPU status...")
    status = service.get_status()
    print(f"Status: {status}")
