"""
Kraken OCR Client

Uses the Kraken library for text line detection and OCR with locally stored
recognition models. Specifically designed for Akkadian cuneiform transliteration
recognition from typeset / hand-copied pages.

Kraken 7.x is the primary target:
  * models are loaded through ``kraken.models.load_models`` (via
    ``RecognitionTaskModel``), which accepts both the new ``.safetensors``
    weights and legacy CoreML ``.mlmodel`` files written by kraken <= 6;
  * recognition runs through ``RecognitionTaskModel.predict`` with a
    ``RecognitionInferenceConfig``.
A thin fallback keeps the client working on a kraken 6 install (legacy
``rpred`` API) so an un-upgraded environment degrades gracefully.
"""

import base64
import logging
import os
import threading
import time
from io import BytesIO
from typing import Dict, Any, List, Optional

from PIL import Image

from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions

# Use root logger to ensure logs appear in console
logger = logging.getLogger()

# Model file formats, in lookup priority order. safetensors is the kraken 7
# default; .mlmodel is the legacy CoreML container (kraken <= 6, still loadable).
MODEL_EXTENSIONS = (".safetensors", ".mlmodel")


def get_kraken_major_version() -> int:
    """Installed kraken major version (0 when kraken is not importable)."""
    try:
        from importlib.metadata import version
        return int(version("kraken").split(".")[0])
    except Exception:
        return 0


def find_model_file(models_dir: str, name: str) -> Optional[str]:
    """Resolve a model *name* (file stem) to an existing model file path.

    Tries each supported extension in priority order so a ``.safetensors``
    file wins over a legacy ``.mlmodel`` of the same name.
    """
    if not name:
        return None
    for ext in MODEL_EXTENSIONS:
        path = os.path.join(models_dir, f"{name}{ext}")
        if os.path.exists(path):
            return path
    return None


def list_model_names(models_dir: str) -> List[str]:
    """Return the unique model names (file stems) present in *models_dir*."""
    names: List[str] = []
    if not os.path.isdir(models_dir):
        return names
    for filename in sorted(os.listdir(models_dir)):
        for ext in MODEL_EXTENSIONS:
            if filename.endswith(ext):
                stem = filename[: -len(ext)]
                if stem not in names:
                    names.append(stem)
    return names


class KrakenOcrClient(BaseOcrClient):
    """
    OCR client using the Kraken library with custom trained models.
    """

    # Default models directory (absolute path based on this file's location)
    MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cured_models")

    # Loaded recognition models are cached per (path, mtime) so repeated page
    # requests don't pay the (multi-second for CoreML) deserialisation cost.
    _model_cache: Dict[str, Any] = {}
    _model_cache_lock = threading.Lock()

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
    def _get_active_model_name(cls) -> Optional[str]:
        """Read the active model name from active_model.txt."""
        active_file = os.path.join(cls.MODELS_DIR, "active_model.txt")
        if os.path.exists(active_file):
            with open(active_file, "r", encoding="utf-8") as f:
                name = f.read().strip()
            if name and find_model_file(cls.MODELS_DIR, name):
                return name
        # Fallback to base
        if find_model_file(cls.MODELS_DIR, "base"):
            return "base"
        return None

    def _resolve_model_path(self, model_name: str) -> str:
        """Resolve model name to actual file path."""
        # "latest" means the currently active model
        if model_name == "latest":
            active = self._get_active_model_name()
            if active:
                return find_model_file(self.MODELS_DIR, active)

        # Direct lookup: a model file with this name (any supported format)
        model_path = find_model_file(self.MODELS_DIR, model_name)
        if model_path:
            return model_path

        # Fallback to active model
        active = self._get_active_model_name()
        if active:
            logger.warning(f"Model '{model_name}' not found, falling back to active model '{active}'")
            return find_model_file(self.MODELS_DIR, active)

        logger.warning(f"Model '{model_name}' not found and no active model set")
        return os.path.join(self.MODELS_DIR, f"{model_name}{MODEL_EXTENSIONS[0]}")

    # ── Model loading ─────────────────────────────────────────────────

    @classmethod
    def _load_recognizer(cls, model_path: str):
        """Load (and cache) a recognition model for the installed kraken version."""
        mtime = os.path.getmtime(model_path)
        with cls._model_cache_lock:
            cached = cls._model_cache.get(model_path)
            if cached and cached["mtime"] == mtime:
                return cached["model"]

        t0 = time.time()
        if get_kraken_major_version() >= 7:
            from kraken.tasks import RecognitionTaskModel
            model = RecognitionTaskModel.load_model(model_path)
        else:  # kraken <= 6 legacy API
            from kraken.lib import models as legacy_models
            model = legacy_models.load_any(model_path)
        logger.info(f"Loaded Kraken model {os.path.basename(model_path)} in {time.time() - t0:.1f}s")

        with cls._model_cache_lock:
            cls._model_cache[model_path] = {"mtime": mtime, "model": model}
        return model

    @staticmethod
    def _inference_device() -> str:
        """Device for recognition: CPU unless KRAKEN_OCR_DEVICE=cuda (and CUDA exists)."""
        want = os.environ.get("KRAKEN_OCR_DEVICE", "cpu").strip().lower()
        if want.startswith("cuda"):
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda"
            except Exception:
                pass
        return "cpu"

    def _recognize(self, model, image: Image.Image, bw_image: Image.Image, seg) -> List[str]:
        """Run line recognition and return one prediction string per segmented line."""
        if get_kraken_major_version() >= 7:
            from kraken.configs import RecognitionInferenceConfig

            # Models declaring a binary input ('1') get the binarized page; all
            # others (grayscale VGSL models, PP-OCRv6) see the original page,
            # matching how their training lines were cropped.
            rec_im = bw_image if getattr(model, "one_channel_mode", None) == "1" else image
            config = RecognitionInferenceConfig(
                batch_size=1,
                num_line_workers=0,  # in-process line extraction (no worker pool inside the server)
                accelerator=self._inference_device(),
                device="auto",
            )
            records = model.predict(rec_im, seg, config)
        else:
            from kraken import rpred
            records = rpred.rpred(model, bw_image, seg)

        return [record.prediction.strip() for record in records]

    # ── OCR ───────────────────────────────────────────────────────────

    def ocr_image(self, image_base64: str, image_width: int, image_height: int, prompt: str = None) -> Dict[str, Any]:
        """
        Process image with Kraken OCR using the Python API (not CLI).

        Args:
            image_base64: Base64 encoded image
            image_width: Width of the image
            image_height: Height of the image
            prompt: Not used by Kraken (uses trained models, not prompts)

        Returns:
            Dict with "lines" (List[str]) and "dimensions" (List[Dimensions])
        """
        try:
            from kraken import binarization, pageseg

            # Decode base64 image
            image_bytes = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_bytes))

            # Convert image mode if needed
            if image.mode == '1':
                image = image.convert('L')
            elif image.mode not in ('L', 'RGB'):
                image = image.convert('RGB')

            # Binarize the image (used for segmentation; also for binary models)
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
            model = self._load_recognizer(self._model_path)

            # Run OCR
            logger.info("Running Kraken OCR...")
            text_lines = self._recognize(model, image, bw_im, seg)
            for text in text_lines:
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
            from kraken import binarization, pageseg  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def list_available_models() -> List[str]:
        """List all available Kraken model names (safetensors or legacy CoreML)."""
        return list_model_names(KrakenOcrClient.MODELS_DIR)
