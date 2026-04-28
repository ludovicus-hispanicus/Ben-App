"""
Segmentation Service

Unified line segmentation pipeline that auto-detects image type (lineart vs photo)
and routes to the appropriate segmentation strategy.

- Lineart: binarize → Kraken pageseg (rule-based line detection)
- Photo: ridge/valley filtering → segmentation (future: trained blla model)
"""

import base64
import logging
import numpy as np
from io import BytesIO
from enum import Enum
from typing import List, Optional, Dict, Any

from PIL import Image
from pydantic import BaseModel

from entities.dimensions import Dimensions

logger = logging.getLogger()


class ImageType(str, Enum):
    LINEART = "lineart"
    PHOTO = "photo"


class SegmentationResult(BaseModel):
    """Standardized output from any segmentation pipeline."""
    lines: List[Dimensions]
    image_type: ImageType
    method: str  # e.g. "kraken_pageseg", "kraken_blla", "ridge_detection"
    error: Optional[str] = None


class SegmentationService:
    """
    Unified entry point for line segmentation.

    Routes to the appropriate pipeline based on image type,
    either auto-detected or explicitly specified.
    """

    # ── Classification thresholds ──────────────────────────────────────

    # Lineart images have bimodal histograms (mostly black + white)
    # with very few mid-range gray values
    BIMODALITY_THRESHOLD = 0.75
    # Lineart images have high edge density (sharp ink lines)
    EDGE_DENSITY_THRESHOLD = 0.15

    # ── Public API ─────────────────────────────────────────────────────

    def segment(self, image_base64: str, image_type: Optional[ImageType] = None) -> SegmentationResult:
        """
        Segment an image into text lines.

        Args:
            image_base64: Base64-encoded image (with or without data URI prefix)
            image_type: Force a specific pipeline. If None, auto-detects.

        Returns:
            SegmentationResult with line bounding boxes
        """
        image_base64 = self._strip_data_uri(image_base64)
        image = self._decode_image(image_base64)

        if image_type is None:
            image_type = self.classify_image(image)

        logger.info(f"Segmentation pipeline: {image_type.value}")

        if image_type == ImageType.LINEART:
            return self._segment_lineart(image)
        else:
            return self._segment_photo(image)

    def classify_image(self, image_or_base64) -> ImageType:
        """
        Classify an image as lineart or photo based on pixel statistics.

        Uses histogram bimodality and edge density — no ML required.
        Lineart (hand copies) are near-binary with sharp edges.
        Photos have continuous tone gradients and softer edges.
        """
        if isinstance(image_or_base64, str):
            image_or_base64 = self._strip_data_uri(image_or_base64)
            image = self._decode_image(image_or_base64)
        else:
            image = image_or_base64

        gray = image.convert("L")
        pixels = np.array(gray).flatten()

        # 1. Bimodality: what fraction of pixels are near black (<64) or near white (>192)?
        near_extremes = np.sum((pixels < 64) | (pixels > 192)) / len(pixels)

        # 2. Edge density via simple gradient magnitude
        arr = np.array(gray, dtype=np.float32)
        if arr.shape[0] > 2 and arr.shape[1] > 2:
            gx = np.abs(np.diff(arr, axis=1))
            gy = np.abs(np.diff(arr, axis=0))
            # Normalize: strong edges (>30 intensity jump) as fraction of total pixels
            edge_density = (np.sum(gx > 30) + np.sum(gy > 30)) / (2 * pixels.size)
        else:
            edge_density = 0

        is_lineart = (
            near_extremes >= self.BIMODALITY_THRESHOLD
            and edge_density >= self.EDGE_DENSITY_THRESHOLD
        )

        result = ImageType.LINEART if is_lineart else ImageType.PHOTO
        logger.info(
            f"Image classification: {result.value} "
            f"(bimodality={near_extremes:.2f}, edge_density={edge_density:.3f})"
        )
        return result

    # ── Lineart pipeline ───────────────────────────────────────────────

    def _segment_lineart(self, image: Image.Image) -> SegmentationResult:
        """
        Segment line art (hand copies) using Kraken's rule-based pageseg.
        No trained model needed — works on binarized images.
        """
        try:
            from kraken import binarization, pageseg

            image = self._ensure_compatible_mode(image)

            logger.info("Lineart pipeline: binarizing...")
            bw_im = binarization.nlbin(image)

            logger.info("Lineart pipeline: segmenting...")
            seg = pageseg.segment(bw_im, text_direction='horizontal-lr')

            lines = self._extract_boxes(seg)
            logger.info(f"Lineart pipeline: detected {len(lines)} lines")

            return SegmentationResult(
                lines=lines,
                image_type=ImageType.LINEART,
                method="kraken_pageseg",
            )

        except ImportError:
            logger.error("Kraken library not installed")
            return SegmentationResult(
                lines=[],
                image_type=ImageType.LINEART,
                method="kraken_pageseg",
                error="Kraken not installed. Run: pip install kraken",
            )
        except Exception as e:
            logger.error(f"Lineart segmentation failed: {e}")
            return SegmentationResult(
                lines=[],
                image_type=ImageType.LINEART,
                method="kraken_pageseg",
                error=str(e),
            )

    # ── Photo pipeline ─────────────────────────────────────────────────

    def _segment_photo(self, image: Image.Image) -> SegmentationResult:
        """
        Segment tablet photographs.

        Current: falls back to Kraken pageseg (same as lineart).
        Future: ridge/valley filtering → trained blla model or U-Net.
        """
        try:
            from kraken import binarization, pageseg

            image = self._ensure_compatible_mode(image)

            logger.info("Photo pipeline: binarizing...")
            bw_im = binarization.nlbin(image)

            logger.info("Photo pipeline: segmenting...")
            seg = pageseg.segment(bw_im, text_direction='horizontal-lr')

            lines = self._extract_boxes(seg)
            logger.info(f"Photo pipeline: detected {len(lines)} lines")

            return SegmentationResult(
                lines=lines,
                image_type=ImageType.PHOTO,
                method="kraken_pageseg",
            )

        except ImportError:
            logger.error("Kraken library not installed")
            return SegmentationResult(
                lines=[],
                image_type=ImageType.PHOTO,
                method="kraken_pageseg",
                error="Kraken not installed. Run: pip install kraken",
            )
        except Exception as e:
            logger.error(f"Photo segmentation failed: {e}")
            return SegmentationResult(
                lines=[],
                image_type=ImageType.PHOTO,
                method="kraken_pageseg",
                error=str(e),
            )

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _strip_data_uri(image_base64: str) -> str:
        """Remove data URI prefix if present."""
        if image_base64.startswith("data:"):
            comma_idx = image_base64.find(",")
            if comma_idx != -1:
                return image_base64[comma_idx + 1:]
        return image_base64

    @staticmethod
    def _decode_image(image_base64: str) -> Image.Image:
        """Decode base64 string to PIL Image."""
        image_bytes = base64.b64decode(image_base64)
        return Image.open(BytesIO(image_bytes))

    @staticmethod
    def _ensure_compatible_mode(image: Image.Image) -> Image.Image:
        """Ensure image is in a mode Kraken can handle."""
        if image.mode == '1':
            return image.convert('L')
        elif image.mode not in ('L', 'RGB'):
            return image.convert('RGB')
        return image

    @staticmethod
    def _extract_boxes(seg) -> List[Dimensions]:
        """Extract bounding boxes from a Kraken segmentation result.

        Handles both the modern Segmentation object (seg.lines with .bbox)
        and the legacy dict fallback ({"boxes": [...], "text_direction": "..."})
        which Kraken returns when it encounters too many connected components.
        """
        boxes = []

        if isinstance(seg, dict):
            # Legacy fallback — list of (x1, y1, x2, y2) tuples
            for bbox in seg.get("boxes", []):
                x1, y1, x2, y2 = bbox
                boxes.append(Dimensions(x=x1, y=y1, width=x2 - x1, height=y2 - y1))
        else:
            # Modern Segmentation container
            for line in seg.lines:
                x1, y1, x2, y2 = line.bbox
                boxes.append(Dimensions(x=x1, y=y1, width=x2 - x1, height=y2 - y1))

        return boxes
