from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple

class BaseOcrClient(ABC):
    @abstractmethod
    def ocr_image(
        self,
        image_base64: str,
        image_width: int,
        image_height: int,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process the image and return a dictionary with keys:
        - "lines": List[str]
        - "dimensions": List[Dimensions] (optional)

        Args:
            image_base64: Base64-encoded image data
            image_width: Width of the image in pixels
            image_height: Height of the image in pixels
            prompt: Optional prompt mode ("plain", "markdown", "dictionary") for VLM models
        """
        pass

    def ocr_images(
        self,
        images: List[Tuple[str, int, int]],
        prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Process multiple images. VLM clients override for true multi-image batching.
        Default: loops calling ocr_image() one at a time."""
        return [self.ocr_image(b64, w, h, prompt) for b64, w, h in images]
