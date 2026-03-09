"""
CuRe OCR Client — BaseOcrClient implementation for cuneiform sign classification.

Pipeline: decode image → detect signs (OpenCV) → classify signs (ResNet18) → assemble results.
"""
import base64
import io
import logging
import os
from typing import Dict, Any, Optional, List

import cv2
import numpy as np
from PIL import Image

from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions
from api.dto.index import Index


# Default models directory (under STORAGE_PATH)
def _get_models_dir() -> str:
    storage_path = os.environ.get("STORAGE_PATH", "data")
    return os.path.join(storage_path, "cure_models")


class CuReOcrClient(BaseOcrClient):
    """
    CuRe sign-level OCR client.

    Detects individual cuneiform signs using OpenCV contour detection,
    then classifies each sign using a trained ResNet18 model.
    """

    def __init__(self, model_name: str = "active"):
        self.model_name = model_name
        self.models_dir = _get_models_dir()
        self._classifier = None
        self._label_service = None

    def _ensure_loaded(self):
        """Lazy-load the classifier and label service."""
        if self._classifier is not None:
            return

        from services.cure_label_service import CuReLabelService
        from services.cure_classifier import get_cached_classifier

        model_path, mapping_path = self._resolve_model_paths()

        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"CuRe model not found: {model_path}. "
                f"Train a model first or import a pre-trained one."
            )

        # Load label mapping
        self._label_service = CuReLabelService()
        if os.path.exists(mapping_path):
            self._label_service.load_mapping(mapping_path)
        else:
            raise FileNotFoundError(
                f"CuRe label mapping not found: {mapping_path}. "
                f"The model requires a corresponding label_mapping.json file."
            )

        self._classifier = get_cached_classifier(model_path, self._label_service.label_list)

    def _resolve_model_paths(self):
        """Resolve model .pt and label_mapping.json paths from model name."""
        if self.model_name == "active":
            model_path = os.path.join(self.models_dir, "active_model.pt")
            mapping_path = os.path.join(self.models_dir, "active_label_mapping.json")
        else:
            model_path = os.path.join(self.models_dir, f"{self.model_name}.pt")
            mapping_path = os.path.join(self.models_dir, f"{self.model_name}_label_mapping.json")
        return model_path, mapping_path

    def ocr_image(
        self,
        image_base64: str,
        image_width: int,
        image_height: int,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Detect and classify cuneiform signs in an image.

        Returns:
            Dict with keys:
            - "lines": List[str] — space-separated sign labels per line
            - "dimensions": List[Dimensions] — one per sign with Index(row, col)
            - "signs": List[dict] — detailed per-sign results
        """
        from services.cure_detection import detect_signs

        # Decode base64 to numpy array
        image_np = self._decode_image(image_base64)

        # Step 1: Detect sign bounding boxes
        detections = detect_signs(image_np)

        if not detections:
            return {"lines": [], "dimensions": [], "signs": []}

        # If no model loaded, return detection-only results
        try:
            self._ensure_loaded()
        except FileNotFoundError as e:
            logging.warning(f"CuRe model not available: {e}. Returning detection-only results.")
            return self._detection_only_result(detections)

        # Step 2: Crop signs and classify in batches per line
        signs_result = []
        lines_dict: Dict[int, List[str]] = {}
        dimensions = []

        # Group detections by line
        line_groups: Dict[int, list] = {}
        for det in detections:
            line_groups.setdefault(det.line_number, []).append(det)

        for line_num in sorted(line_groups.keys()):
            line_dets = line_groups[line_num]

            # Crop each sign from the image
            crops = []
            for det in line_dets:
                y_start = max(0, det.y)
                x_start = max(0, det.x)
                y_end = min(image_np.shape[0], det.y + det.height)
                x_end = min(image_np.shape[1], det.x + det.width)
                crop = image_np[y_start:y_end, x_start:x_end]
                if crop.size > 0:
                    crops.append(crop)
                else:
                    crops.append(np.zeros((64, 64, 3), dtype=np.uint8))

            # Batch classify
            batch_results = self._classifier.classify_batch(crops)

            line_labels = []
            for det, preds in zip(line_dets, batch_results):
                top_label = preds[0][0] if preds else "?"
                top_conf = preds[0][1] if preds else 0.0
                unicode_char = self._label_service.get_unicode(top_label)

                line_labels.append(top_label)

                dimensions.append(Dimensions(
                    x=float(det.x),
                    y=float(det.y),
                    width=float(det.width),
                    height=float(det.height),
                    index=Index(row=det.line_number, col=det.position_in_line),
                ))

                signs_result.append({
                    "label": top_label,
                    "unicode": unicode_char,
                    "confidence": round(top_conf, 4),
                    "line": det.line_number,
                    "position": det.position_in_line,
                    "bbox": {
                        "x": det.x,
                        "y": det.y,
                        "width": det.width,
                        "height": det.height,
                    },
                    "top3": [
                        {
                            "label": lbl,
                            "unicode": self._label_service.get_unicode(lbl),
                            "confidence": round(conf, 4),
                        }
                        for lbl, conf in preds[:3]
                    ],
                })

            lines_dict[line_num] = line_labels

        # Assemble lines as space-separated labels
        lines = []
        for line_num in sorted(lines_dict.keys()):
            lines.append(" ".join(lines_dict[line_num]))

        return {"lines": lines, "dimensions": dimensions, "signs": signs_result}

    def _detection_only_result(self, detections) -> Dict[str, Any]:
        """Return results with bounding boxes but no classification."""
        dimensions = []
        lines_dict: Dict[int, int] = {}

        for det in detections:
            dimensions.append(Dimensions(
                x=float(det.x),
                y=float(det.y),
                width=float(det.width),
                height=float(det.height),
                index=Index(row=det.line_number, col=det.position_in_line),
            ))
            lines_dict[det.line_number] = lines_dict.get(det.line_number, 0) + 1

        lines = [f"[{count} signs detected]" for count in lines_dict.values()]
        return {"lines": lines, "dimensions": dimensions, "signs": []}

    @staticmethod
    def _decode_image(image_base64: str) -> np.ndarray:
        """Decode a base64 image string to a BGR numpy array."""
        # Strip data URL prefix if present
        if image_base64.startswith("data:"):
            comma_idx = image_base64.find(",")
            if comma_idx != -1:
                image_base64 = image_base64[comma_idx + 1:]

        image_data = base64.b64decode(image_base64)
        pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")
        np_array = np.array(pil_image)
        # Convert RGB to BGR for OpenCV
        return cv2.cvtColor(np_array, cv2.COLOR_RGB2BGR)

    @staticmethod
    def is_available() -> bool:
        """Check if CuRe has at least one model available."""
        models_dir = _get_models_dir()
        active_model = os.path.join(models_dir, "active_model.pt")
        return os.path.exists(active_model)

    @staticmethod
    def list_available_models() -> List[str]:
        """List all trained CuRe model names."""
        models_dir = _get_models_dir()
        if not os.path.exists(models_dir):
            return []
        models = []
        for f in os.listdir(models_dir):
            if f.endswith(".pt") and f != "active_model.pt":
                models.append(f.replace(".pt", ""))
        return models
