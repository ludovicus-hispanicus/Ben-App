"""
TrOCR OCR Client

Wraps trocr_training_service to follow the BaseOcrClient interface.
TrOCR is a line-level OCR model: each image is treated as a single text line.
Best used with pre-segmented line images (e.g., from YOLO segmentation).

For multi-line images, the client splits the image into horizontal strips
using projection-based line segmentation, runs TrOCR on each strip, and
combines the results.
"""

import base64
import logging
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from clients.base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions

logger = logging.getLogger(__name__)

# If aspect ratio (width/height) is below this, treat as multi-line image
_SINGLE_LINE_ASPECT_THRESHOLD = 3.0


def _segment_lines(image: Image.Image) -> List[Tuple[int, int]]:
    """
    Segment an image into horizontal line strips using projection profile.
    Returns list of (y_start, y_end) tuples for each detected line.
    """
    gray = np.array(image.convert("L"))

    # Binarize: dark pixels = ink (value < threshold)
    threshold = np.mean(gray) - 0.5 * np.std(gray)
    binary = gray < threshold

    # Horizontal projection: count ink pixels per row
    projection = binary.sum(axis=1)

    # Find line regions: rows with ink above a noise threshold
    noise_threshold = max(1, projection.max() * 0.05)
    in_line = projection > noise_threshold

    lines = []
    start = None
    for y, active in enumerate(in_line):
        if active and start is None:
            start = y
        elif not active and start is not None:
            if y - start > 5:  # minimum line height to filter noise
                lines.append((start, y))
            start = None
    if start is not None and len(gray) - start > 5:
        lines.append((start, len(gray)))

    return lines


class TrOCROcrClient(BaseOcrClient):
    """OCR client using fine-tuned TrOCR for line-level transliteration recognition."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name
        logger.info(f"Initialized TrOCROcrClient with model: {model_name or 'active'}")

    def ocr_image(
        self,
        image_base64: str,
        image_width: int,
        image_height: int,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        from services.trocr_training_service import trocr_training_service

        # Decode image
        image_bytes = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_bytes))

        # Convert to grayscale (matching Kraken training line image format)
        gray_image = image.convert("L")
        w, h = gray_image.size
        aspect = w / max(1, h)

        logger.info(
            f"TrOCR OCR: model={self.model_name or 'active'}, "
            f"size={w}x{h}, aspect={aspect:.1f}:1"
        )

        # Decide: single-line or multi-line processing
        if aspect >= _SINGLE_LINE_ASPECT_THRESHOLD:
            # Image is wide enough to be a single line — process directly
            text = trocr_training_service.recognize_line(
                image=gray_image,
                model_name=self.model_name,
            )
            if not text or not text.strip():
                return {"lines": [], "dimensions": []}

            return {
                "lines": [text.strip()],
                "dimensions": [
                    Dimensions(x=0, y=0, width=image_width, height=image_height)
                ],
            }

        # Multi-line image — segment into horizontal line strips
        line_regions = _segment_lines(gray_image)
        logger.info(f"TrOCR: detected {len(line_regions)} line regions in multi-line image")

        if not line_regions:
            # Fallback: treat entire image as one line
            text = trocr_training_service.recognize_line(
                image=gray_image,
                model_name=self.model_name,
            )
            if not text or not text.strip():
                return {"lines": [], "dimensions": []}
            return {
                "lines": [text.strip()],
                "dimensions": [
                    Dimensions(x=0, y=0, width=image_width, height=image_height)
                ],
            }

        # Crop all line strips
        line_images = [
            gray_image.crop((0, y_start, w, y_end))
            for y_start, y_end in line_regions
        ]

        # Batch inference: single model load for all lines
        texts = trocr_training_service.recognize_lines(
            images=line_images,
            model_name=self.model_name,
        )

        lines = []
        dimensions = []
        scale_y = image_height / max(1, h)

        for text, (y_start, y_end) in zip(texts, line_regions):
            if text and text.strip():
                lines.append(text.strip())
                dimensions.append(Dimensions(
                    x=0,
                    y=int(y_start * scale_y),
                    width=image_width,
                    height=int((y_end - y_start) * scale_y),
                ))

        if not lines:
            return {"lines": [], "dimensions": []}

        logger.info(f"TrOCR: recognized {len(lines)} lines from {len(line_regions)} regions")
        return {
            "lines": lines,
            "dimensions": dimensions,
        }
