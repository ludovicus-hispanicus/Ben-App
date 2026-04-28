"""
Image resize utility for reducing resolution before OCR.
Supports both blind scale factor and DPI-aware resizing.
"""
import base64
import io
import logging
from typing import Tuple

from PIL import Image

logger = logging.getLogger(__name__)

# Fallback DPI when image metadata has no DPI info.
# Most scanned cuneiform tablets are 300-600 DPI; 300 is a safe lower bound.
_DEFAULT_SOURCE_DPI = 300


def _get_image_dpi(img: Image.Image) -> float:
    """Extract DPI from image metadata. Returns the average of x/y DPI.
    Falls back to _DEFAULT_SOURCE_DPI if metadata is missing or unreliable.
    """
    dpi = img.info.get("dpi")
    if dpi and isinstance(dpi, (tuple, list)) and len(dpi) >= 2:
        x_dpi, y_dpi = float(dpi[0]), float(dpi[1])
        # Sanity check: ignore clearly wrong values (e.g. 0, 1, or 96 from screenshots)
        if x_dpi >= 150 and y_dpi >= 150:
            return (x_dpi + y_dpi) / 2.0
    return _DEFAULT_SOURCE_DPI


def resize_to_target_dpi(image_bytes: bytes, target_dpi: int) -> Tuple[bytes, float]:
    """Resize image so its effective resolution matches target_dpi.

    Reads the actual DPI from image metadata to compute the correct scale.
    Never upscales — if the image is already at or below target_dpi, returns it unchanged.

    Returns:
        (resized_bytes, scale_applied) — scale_applied is 1.0 if no resize happened.
    """
    if target_dpi <= 0:
        return image_bytes, 1.0

    try:
        img = Image.open(io.BytesIO(image_bytes))
        source_dpi = _get_image_dpi(img)
        img.close()

        if source_dpi <= target_dpi:
            # Already at or below target — no resize needed
            return image_bytes, 1.0

        scale = target_dpi / source_dpi
        resized = resize_image_bytes(image_bytes, scale)
        return resized, scale
    except Exception as e:
        logger.error(f"DPI-aware resize failed (target_dpi={target_dpi}): {e}")
        return image_bytes, 1.0


def resize_image_bytes(image_bytes: bytes, scale: float) -> bytes:
    """Resize image bytes by a scale factor. Returns original if scale >= 1.0."""
    if scale >= 1.0 or scale <= 0:
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))
        orig_format = img.format or "PNG"
        orig_w, orig_h = img.size

        new_w = max(1, int(orig_w * scale))
        new_h = max(1, int(orig_h * scale))

        resized = img.resize((new_w, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        save_kwargs = {}
        if orig_format.upper() in ("JPEG", "JPG"):
            save_kwargs["quality"] = 95
        resized.save(buf, format=orig_format, **save_kwargs)

        logger.info(f"Resized image from {orig_w}x{orig_h} to {new_w}x{new_h} (scale={scale:.3f})")
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Failed to resize image (scale={scale}): {e}")
        return image_bytes


def resize_base64_image(image_base64: str, scale: float) -> str:
    """Resize a base64-encoded image by a scale factor."""
    if scale >= 1.0 or scale <= 0:
        return image_base64

    image_bytes = base64.b64decode(image_base64)
    resized_bytes = resize_image_bytes(image_bytes, scale)
    return base64.b64encode(resized_bytes).decode("utf-8")
