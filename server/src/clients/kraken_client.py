"""
Kraken OCR Client

Uses Kraken library for text line detection and OCR using trained .mlmodel files.
Specifically designed for Akkadian cuneiform text recognition.
"""

import base64
import logging
import os
from io import BytesIO
from typing import Dict, Any, List

from PIL import Image

from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions

# Use root logger to ensure logs appear in console
logger = logging.getLogger()


class KrakenOcrClient(BaseOcrClient):
    """
    OCR client using Kraken library with custom trained models.
    """

    # Default models directory (absolute path based on this file's location)
    MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cured_models")

    def __init__(self, model_name: str = "latest"):
        """
        Initialize Kraken OCR client.

        Args:
            model_name: Name of the model to use ("latest" for active model, or any model name)
        """
        self.model_name = model_name
        self._model_path = self._resolve_model_path(model_name)
        logger.info(f"Initialized KrakenOcrClient with model: {model_name}")
        logger.info(f"Model path: {self._model_path}")
        logger.info(f"Model exists: {os.path.exists(self._model_path)}")

    @classmethod
    def _get_active_model_name(cls) -> str:
        """Read the active model name from active_model.txt."""
        active_file = os.path.join(cls.MODELS_DIR, "active_model.txt")
        if os.path.exists(active_file):
            with open(active_file, "r") as f:
                name = f.read().strip()
            if name and os.path.exists(os.path.join(cls.MODELS_DIR, f"{name}.mlmodel")):
                return name
        # Fallback to base
        if os.path.exists(os.path.join(cls.MODELS_DIR, "base.mlmodel")):
            return "base"
        return None

    def _resolve_model_path(self, model_name: str) -> str:
        """Resolve model name to actual file path."""
        # "latest" means the currently active model
        if model_name == "latest":
            active = self._get_active_model_name()
            if active:
                return os.path.join(self.MODELS_DIR, f"{active}.mlmodel")

        # Direct lookup: check if .mlmodel file with this name exists
        model_path = os.path.join(self.MODELS_DIR, f"{model_name}.mlmodel")
        if os.path.exists(model_path):
            return model_path

        # Fallback to active model
        active = self._get_active_model_name()
        if active:
            logger.warning(f"Model '{model_name}' not found, falling back to active model '{active}'")
            return os.path.join(self.MODELS_DIR, f"{active}.mlmodel")

        logger.warning(f"Model '{model_name}' not found and no active model set")
        return os.path.join(self.MODELS_DIR, f"{model_name}.mlmodel")

    def ocr_image(self, image_base64: str, image_width: int, image_height: int, prompt: str = None) -> Dict[str, Any]:
        """
        Process image with Kraken OCR using Python API (not CLI).

        Args:
            image_base64: Base64 encoded image
            image_width: Width of the image
            image_height: Height of the image
            prompt: Not used by Kraken (uses trained models, not prompts)

        Returns:
            Dict with "lines" (List[str]) and "dimensions" (List[Dimensions])
        """
        try:
            from kraken import binarization, pageseg, rpred
            from kraken.lib import models

            # Decode base64 image
            image_bytes = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_bytes))

            # Convert image mode if needed
            if image.mode == '1':
                image = image.convert('L')
            elif image.mode not in ('L', 'RGB'):
                image = image.convert('RGB')

            # Binarize the image
            logger.info("Binarizing image...")
            bw_im = binarization.nlbin(image)

            # Segment to find text lines
            logger.info("Segmenting image...")
            seg = pageseg.segment(bw_im, text_direction='horizontal-lr')
            logger.info(f"Kraken detected {len(seg.lines)} line bounding boxes")

            if len(seg.lines) == 0:
                logger.warning("No bounding boxes detected by Kraken")
                return {"lines": [], "dimensions": []}

            # Extract bounding boxes
            boxes = []
            for line in seg.lines:
                x1, y1, x2, y2 = line.bbox
                boxes.append(Dimensions(
                    x=x1,
                    y=y1,
                    width=x2 - x1,
                    height=y2 - y1
                ))

            # Load the OCR model
            logger.info(f"Loading Kraken model from: {self._model_path}")
            model = models.load_any(self._model_path)

            # Run OCR using Python API (avoids CLI path issues on Windows)
            logger.info("Running Kraken OCR...")
            pred = rpred.rpred(model, bw_im, seg)

            # Collect predictions
            text_lines = []
            for record in pred:
                text = record.prediction.strip()
                text_lines.append(text)
                logger.debug(f"OCR line: {text}")

            logger.info(f"Kraken OCR completed: {len(text_lines)} lines")

            return {
                "lines": text_lines,
                "dimensions": boxes
            }

        except ImportError as e:
            logger.error(f"Kraken library not installed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "lines": [],
                "dimensions": [],
                "error": "Kraken library not installed. Run: pip install kraken"
            }
        except Exception as e:
            logger.error(f"Kraken OCR failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "lines": [],
                "dimensions": [],
                "error": str(e)
            }

    @staticmethod
    def is_available() -> bool:
        """Check if Kraken is installed and available."""
        try:
            from kraken import binarization, pageseg
            return True
        except ImportError:
            return False

    @staticmethod
    def list_available_models() -> List[str]:
        """List all available Kraken models."""
        models = []
        models_dir = KrakenOcrClient.MODELS_DIR

        if not os.path.exists(models_dir):
            return models

        for filename in os.listdir(models_dir):
            if filename.endswith(".mlmodel"):
                # Add the model name (without extension)
                model_name = filename.replace(".mlmodel", "")
                models.append(model_name)

        return models
