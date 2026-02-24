import os
import re
import json
import base64
import logging
from io import BytesIO
from typing import List, Dict, Optional

import requests
from PIL import Image

from entities.dimensions import Dimensions


class NemotronClient:
    """
    Unified client for Nemotron Parse VLM OCR.

    Supports two modes:
      - "api"   : NVIDIA cloud API (or self-hosted NIM) via HTTP
      - "local" : HuggingFace transformers running on local CUDA GPU
    """

    CLOUD_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
    HF_MODEL_ID = "nvidia/NVIDIA-Nemotron-Parse-v1.1"

    def __init__(self, mode: str = "api", api_key: str = None):
        self.mode = mode
        self._model = None
        self._processor = None
        self._device = None

        if mode == "api":
            self.api_url = os.environ.get("VLM_OCR_URL", self.CLOUD_API_URL)
            # Use provided api_key or fall back to environment variable
            self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
            if not self.api_key:
                logging.warning("NVIDIA_API_KEY not set — cloud API calls will fail")
        elif mode == "local":
            self._init_local_model()
        else:
            raise ValueError(f"Unknown Nemotron mode: {mode}. Use 'api' or 'local'.")

    # ------------------------------------------------------------------ #
    #  Local model initialisation (lazy-loaded once)
    # ------------------------------------------------------------------ #

    def _init_local_model(self):
        import torch
        from transformers import AutoModel, AutoProcessor

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        if self._device == "cpu":
            logging.warning("CUDA not available — local Nemotron will run on CPU (very slow)")
        else:
            gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
            logging.info(f"GPU: {torch.cuda.get_device_name(0)}, VRAM: {gpu_mem:.1f} GB")

        logging.info(f"Loading {self.HF_MODEL_ID} with float16...")
        self._processor = AutoProcessor.from_pretrained(
            self.HF_MODEL_ID, trust_remote_code=True
        )

        # Nemotron-Parse is <1B params (~885M), ~1.7GB in float16
        # Load entirely on GPU for fastest inference (no CPU offloading)
        if self._device == "cuda":
            torch.cuda.empty_cache()
            self._model = AutoModel.from_pretrained(
                self.HF_MODEL_ID,
                trust_remote_code=True,
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True,
            ).to("cuda")
            logging.info("Model loaded entirely on GPU (float16, ~1.7GB VRAM)")
        else:
            self._model = AutoModel.from_pretrained(
                self.HF_MODEL_ID,
                trust_remote_code=True,
                torch_dtype=torch.float32,
                low_cpu_mem_usage=True,
            )
        self._model.eval()
        logging.info("Nemotron-Parse local model ready.")

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def ocr_image(
        self,
        image_base64: str,
        image_width: int,
        image_height: int,
        prompt: Optional[str] = None,
    ) -> Dict:
        """
        Run OCR on a base64-encoded image.

        Args:
            prompt: Not used by Nemotron (uses built-in document parsing)

        Returns:
            {"lines": List[str], "dimensions": List[Dimensions]}
        """
        if self.mode == "api":
            return self._ocr_cloud(image_base64, image_width, image_height)
        else:
            return self._ocr_local(image_base64, image_width, image_height)

    # ------------------------------------------------------------------ #
    #  Cloud API mode
    # ------------------------------------------------------------------ #

    def _detect_mime_type(self, image_base64: str) -> str:
        """Detect image MIME type from base64 data."""
        try:
            image_data = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_data))
            fmt = (image.format or "PNG").upper()
            if fmt == "JPEG" or fmt == "JPG":
                return "image/jpeg"
            return "image/png"
        except Exception:
            return "image/png"

    def _ocr_cloud(
        self,
        image_base64: str,
        image_width: int,
        image_height: int,
    ) -> Dict:
        # Detect mime type from original image (no preprocessing to preserve quality)
        mime_type = self._detect_mime_type(image_base64)

        # Validate API key - must contain only ASCII characters for HTTP headers
        api_key = self.api_key or ""

        # Check for non-ASCII characters and warn
        non_ascii_chars = [c for c in api_key if ord(c) > 127]
        if non_ascii_chars:
            logging.error(f"NVIDIA API key contains invalid characters: {non_ascii_chars}")
            logging.error("Please regenerate your NVIDIA API key - it must contain only ASCII characters.")
            logging.error("Go to https://build.nvidia.com and generate a new API key.")
            # Try to sanitize but this will likely make the key invalid
            api_key = ''.join(c for c in api_key if ord(c) < 128)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": "nvidia/nemotron-parse",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            },
                        }
                    ],
                }
            ],
            "tools": [
                {"type": "function", "function": {"name": "markdown_bbox"}}
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": "markdown_bbox"}
            },
            "max_tokens": 8192,
        }

        resp = requests.post(self.api_url, headers=headers, json=payload, timeout=120)

        # Log response for debugging
        if resp.status_code != 200:
            logging.error(f"NVIDIA API error {resp.status_code}: {resp.text[:500]}")

        resp.raise_for_status()
        data = resp.json()

        # Log raw response for debugging
        logging.debug(f"NVIDIA API response: {json.dumps(data)[:1000]}")

        return self._parse_cloud_response(data, image_width, image_height)

    def _parse_cloud_response(
        self, data: dict, image_width: int, image_height: int
    ) -> Dict:
        lines: List[str] = []
        dimensions: List[Dimensions] = []

        try:
            tool_calls = data["choices"][0]["message"]["tool_calls"]
            arguments_str = tool_calls[0]["function"]["arguments"]
            elements = json.loads(arguments_str)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logging.error(f"Failed to parse Nemotron cloud response: {e}")
            return {"lines": [], "dimensions": []}

        # API returns nested array: [[elements_page1], [elements_page2], ...]
        # Flatten all pages into a single list of elements
        for page_elements in elements:
            if not isinstance(page_elements, list):
                continue
            for elem in page_elements:
                if not isinstance(elem, dict):
                    continue
                text = elem.get("text", "").strip()
                if not text:
                    continue

                # Clean HTML tags and unknown placeholders
                text = self._clean_html_tags(text)

                bbox = elem.get("bbox", {})
                xmin = bbox.get("xmin", 0)
                ymin = bbox.get("ymin", 0)
                xmax = bbox.get("xmax", 0)
                ymax = bbox.get("ymax", 0)

                lines.append(text)
                dimensions.append(
                    Dimensions(
                        x=int(xmin * image_width),
                        y=int(ymin * image_height),
                        width=int((xmax - xmin) * image_width),
                        height=int((ymax - ymin) * image_height),
                    )
                )

        return {"lines": lines, "dimensions": dimensions}

    # ------------------------------------------------------------------ #
    #  Local model mode
    # ------------------------------------------------------------------ #

    # Task prompt for Nemotron Parse - tells it to predict bboxes, classes, and output markdown
    TASK_PROMPT = "</s><s><predict_bbox><predict_classes><output_markdown>"

    def _ocr_local(
        self,
        image_base64: str,
        image_width: int,
        image_height: int,
    ) -> Dict:
        import torch

        try:
            # Clear GPU cache before inference
            if self._device == "cuda":
                torch.cuda.empty_cache()

            image = Image.open(BytesIO(base64.b64decode(image_base64))).convert("RGB")
            logging.info(f"[Nemotron OCR] Input image size: {image.size}, mode: {image.mode}")

            inputs = self._processor(
                images=[image],
                text=self.TASK_PROMPT,
                return_tensors="pt",
                add_special_tokens=False
            )

            inputs = {k: v.to(self._device) if hasattr(v, 'to') else v for k, v in inputs.items()}

            with torch.no_grad():
                output_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=4096,
                    do_sample=False,
                    use_cache=False,
                )

            raw_text = self._processor.batch_decode(output_ids, skip_special_tokens=True)[0]

            # Debug: log raw model output
            logging.info(f"[Nemotron OCR] Raw model output length: {len(raw_text)}")
            logging.debug(f"[Nemotron OCR] Raw output (first 500 chars): {raw_text[:500]}")

            # Clean up
            del inputs, output_ids
            if self._device == "cuda":
                torch.cuda.empty_cache()

            return self._parse_local_response(raw_text, image_width, image_height)

        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "CUDA" in str(e):
                logging.error(f"CUDA out of memory error: {e}")
                if self._device == "cuda":
                    torch.cuda.empty_cache()
                raise RuntimeError(
                    f"GPU out of memory processing image ({image_width}x{image_height}). "
                    f"Try selecting a smaller region with the bounding box tool."
                ) from e
            raise

    # Regex to strip HTML tags from cloud API output
    _HTML_TAG_PATTERN = re.compile(r'</?(?:sub|sup|u|b|i|em|strong|span|div|p)(?:\s[^>]*)?>')

    # Regex for \(\unknown\) placeholders
    _UNKNOWN_PATTERN = re.compile(r'\\?\(\\?unknown\\?\)')

    @staticmethod
    def _clean_html_tags(text: str) -> str:
        """Remove HTML formatting tags from text while preserving content."""
        # Remove HTML tags
        text = NemotronClient._HTML_TAG_PATTERN.sub('', text)
        # Replace \(\unknown\) with a cleaner placeholder
        text = NemotronClient._UNKNOWN_PATTERN.sub('[?]', text)
        return text.strip()

    # Regex for local model output:  <x_0.29><y_0.33>text<x_0.48><y_0.35><class_List-item>
    _LINE_PATTERN = re.compile(
        r"<x_([\d.]+)><y_([\d.]+)>"  # start x, y
        r"(.*?)"                      # text content
        r"<x_([\d.]+)><y_([\d.]+)>"  # end x, y
        r"<class_([^>]+)>"           # class label
    )

    def _parse_local_response(
        self, raw_text: str, image_width: int, image_height: int
    ) -> Dict:
        lines: List[str] = []
        dimensions: List[Dimensions] = []

        # Count regex matches
        matches = list(self._LINE_PATTERN.finditer(raw_text))
        logging.info(f"[Nemotron OCR] Found {len(matches)} regex matches in raw output")

        # If no matches found but we have output, log the raw text for debugging
        if len(matches) == 0 and len(raw_text) > 0:
            logging.warning(f"[Nemotron OCR] Parsing failed - no bbox tags found in model output")
            logging.warning(f"[Nemotron OCR] Raw output (truncated): {raw_text[:1000]}")
            # Check if output looks like markdown without bboxes
            if '<x_' not in raw_text:
                logging.warning("[Nemotron OCR] Output contains no <x_...> coordinate tags - model may have returned plain text")

        for match in matches:
            x_start = float(match.group(1))
            y_start = float(match.group(2))
            text = match.group(3).strip()
            x_end = float(match.group(4))
            y_end = float(match.group(5))
            # class_label = match.group(6)  # available if needed for filtering

            if not text:
                continue

            logging.info(f"[Nemotron OCR] Line {len(lines)+1}: {text[:100]}...")
            lines.append(text)
            dimensions.append(
                Dimensions(
                    x=int(x_start * image_width),
                    y=int(y_start * image_height),
                    width=int((x_end - x_start) * image_width),
                    height=int((y_end - y_start) * image_height),
                )
            )

        return {"lines": lines, "dimensions": dimensions}
