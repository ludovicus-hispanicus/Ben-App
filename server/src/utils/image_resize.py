"""
Image resize utility for reducing resolution before OCR.
Uses scale factor (not DPI) since source DPI is unreliable.
"""
import base64
import io
import logging
from PIL import Image

logger = logging.getLogger(__name__)


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

        logger.info(f"Resized image from {orig_w}x{orig_h} to {new_w}x{new_h} (scale={scale})")
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
