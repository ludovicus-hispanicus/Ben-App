"""
CuRe Sign Classifier — ResNet18-based cuneiform sign classification.

Adapted from CuneiformOcr/src/train.py inference logic.
Loads a trained ResNet18 model and classifies 64x64 sign crops.
"""
import logging
import os
from typing import List, Tuple, Optional

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision
import torchvision.transforms as transforms


# Module-level cache for the active classifier (avoids reloading on every request)
_cached_classifier: Optional["CuReClassifier"] = None
_cached_model_path: Optional[str] = None


class CuReClassifier:
    """ResNet18-based cuneiform sign classifier."""

    IMAGE_SIZE = 64

    def __init__(self, model_path: str, label_list: List[str]):
        """
        Load a trained CuRe model.

        Args:
            model_path: Path to the .pt state_dict file
            label_list: Ordered list of label names (index matches model output)
        """
        self.model_path = model_path
        self.label_list = label_list
        self.num_classes = len(label_list)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.transform = transforms.Compose([transforms.ToTensor()])

        self.model = self._load_model(model_path)
        logging.info(
            f"CuRe classifier loaded: {self.num_classes} classes, "
            f"device={self.device}, model={os.path.basename(model_path)}"
        )

    def _load_model(self, model_path: str) -> nn.Module:
        """Load ResNet18 with custom FC layer from state dict."""
        model = torchvision.models.resnet18(weights=None)
        num_ftrs = model.fc.in_features
        model.fc = nn.Linear(num_ftrs, self.num_classes)
        model = model.double()  # float64 to match original CuneiformOcr
        model.to(self.device)

        state_dict = torch.load(model_path, map_location=self.device, weights_only=True)
        model.load_state_dict(state_dict)
        model.eval()
        return model

    def _preprocess_crop(self, crop: np.ndarray) -> torch.Tensor:
        """Resize and normalize a sign crop to model input format."""
        resized = cv2.resize(crop, (self.IMAGE_SIZE, self.IMAGE_SIZE))
        # Ensure RGB, 3 channels
        if len(resized.shape) == 2:
            resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB)
        elif resized.shape[2] == 4:
            resized = cv2.cvtColor(resized, cv2.COLOR_BGRA2RGB)
        elif resized.shape[2] == 3:
            resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

        # Normalize to [0, 1] float64 (matching original CuneiformOcr)
        normalized = resized.astype(np.float64) / 255.0
        tensor = self.transform(normalized)
        return tensor.to(self.device)

    def classify_single(self, crop: np.ndarray, top_k: int = 3) -> List[Tuple[str, float]]:
        """
        Classify a single sign crop.

        Args:
            crop: BGR numpy array of the sign crop (any size, will be resized)
            top_k: Number of top predictions to return

        Returns:
            List of (label, confidence) tuples, sorted by confidence descending.
        """
        tensor = self._preprocess_crop(crop).unsqueeze(0)
        with torch.no_grad():
            scores = self.model(tensor)
            probs = torch.softmax(scores, dim=1)
            top_probs, top_indices = torch.topk(probs, min(top_k, self.num_classes), dim=1)

        results = []
        for prob, idx in zip(top_probs[0], top_indices[0]):
            label = self.label_list[idx.item()]
            results.append((label, prob.item()))
        return results

    def classify_batch(
        self, crops: List[np.ndarray], top_k: int = 3
    ) -> List[List[Tuple[str, float]]]:
        """
        Classify a batch of sign crops.

        Args:
            crops: List of BGR numpy arrays (any size, will be resized to 64x64)
            top_k: Number of top predictions per crop

        Returns:
            List of prediction lists. Each prediction is (label, confidence).
        """
        if not crops:
            return []

        tensors = [self._preprocess_crop(c) for c in crops]
        batch = torch.stack(tensors)

        with torch.no_grad():
            scores = self.model(batch)
            probs = torch.softmax(scores, dim=1)
            top_probs, top_indices = torch.topk(probs, min(top_k, self.num_classes), dim=1)

        results = []
        for i in range(len(crops)):
            preds = []
            for prob, idx in zip(top_probs[i], top_indices[i]):
                label = self.label_list[idx.item()]
                preds.append((label, prob.item()))
            results.append(preds)
        return results


def get_cached_classifier(model_path: str, label_list: List[str]) -> CuReClassifier:
    """
    Get or create a cached classifier instance.
    Reuses the cached instance if the model path matches.
    """
    global _cached_classifier, _cached_model_path
    if _cached_classifier is None or _cached_model_path != model_path:
        logging.info(f"Loading CuRe classifier from {model_path}")
        _cached_classifier = CuReClassifier(model_path, label_list)
        _cached_model_path = model_path
    return _cached_classifier


def clear_cached_classifier():
    """Clear the cached classifier (e.g., when switching active model)."""
    global _cached_classifier, _cached_model_path
    _cached_classifier = None
    _cached_model_path = None
