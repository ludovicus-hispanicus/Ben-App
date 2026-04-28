import os
import logging
import base64
from typing import List

from starlette.background import BackgroundTasks
from PIL import Image
from io import BytesIO

from api.dto.cured_result import CuredResultDto
from api.dto.get_predictions import CureDGetTransliterationsDto
from entities.dimensions import Dimensions
from clients.nemotron_client import NemotronClient
from common.env_vars import NEMOTRON_MODE


# Initialize Nemotron client once at module load
_nemotron_mode = os.environ.get(NEMOTRON_MODE, "api")
_nemotron_client = NemotronClient(mode=_nemotron_mode)


class CuredHandler:

    @staticmethod
    def _strip_data_url_prefix(data: str) -> str:
        """Strip data URL prefix (e.g., 'data:image/png;base64,') if present."""
        if data.startswith("data:"):
            # Find the comma that separates the prefix from the actual data
            comma_idx = data.find(",")
            if comma_idx != -1:
                return data[comma_idx + 1:]
        return data

    @staticmethod
    def get_transliterations(dto: CureDGetTransliterationsDto, background_tasks: BackgroundTasks):
        """
        Run Nemotron OCR on the provided base64 image.

        Returns CuredResultDto with detected text lines and bounding boxes.
        """
        # Strip data URL prefix if present (frontend sends data:image/png;base64,...)
        image_base64 = CuredHandler._strip_data_url_prefix(dto.image)

        # Get original image dimensions
        orig_width, orig_height = CuredHandler._get_image_dimensions(image_base64)

        # If bounding box is provided, crop the image to that region
        # This is useful for memory-constrained local models (like Nemotron on 8GB GPU)
        crop_offset_x, crop_offset_y = 0, 0
        if dto.boundingBox is not None:
            image_base64, crop_offset_x, crop_offset_y = CuredHandler._crop_to_bounding_box(
                image_base64, dto.boundingBox
            )
            logging.info(f"Cropped image to bounding box: {dto.boundingBox}")

        # Get dimensions of the (possibly cropped) image for coordinate conversion
        image_width, image_height = CuredHandler._get_image_dimensions(image_base64)

        # Apply global image scale reduction
        from common.app_settings import get_image_scale
        from utils.image_resize import resize_base64_image
        scale = get_image_scale()
        pre_scale_width, pre_scale_height = image_width, image_height
        if scale < 1.0:
            image_base64 = resize_base64_image(image_base64, scale)
            image_width, image_height = CuredHandler._get_image_dimensions(image_base64)

        # Select correct client via Factory
        from clients.ocr_factory import OCRFactory
        
        # Use factory to get the client (gemini, openai, or nemotron)
        ocr_client = OCRFactory.get_client(
            provider_name=dto.model, 
            api_key=dto.apiKey
        )

        # For TEI Lex-0 mode with a two-stage pipeline:
        # Stage 1 uses "dictionary" prompt for OCR (better text extraction)
        # Stage 2 converts the text to TEI XML using a separate model
        is_tei_two_stage = dto.prompt == "tei_lex0" and dto.teiModel
        ocr_prompt = "dictionary" if is_tei_two_stage else dto.prompt

        logging.info(
            f"Processing OCR with provider: {dto.model}, prompt: {ocr_prompt}"
            f"{f', tei_stage2: {dto.teiProvider}:{dto.teiModel}' if is_tei_two_stage else ''}"
        )

        # Stage 1: Run OCR
        result = ocr_client.ocr_image(
            image_base64=image_base64,
            image_width=image_width,
            image_height=image_height,
            prompt=ocr_prompt,
        )

        text_lines = result.get("lines", [])
        boxes = result.get("dimensions", [])

        # Log OCR result details
        ocr_error = result.get("error")
        if ocr_error:
            logging.error(f"OCR returned error: {ocr_error}")
        logging.info(f"OCR result: {len(text_lines)} lines, {len(boxes)} boxes")

        # Clean up newlines in text
        text_lines = [line.replace("\n", "") for line in text_lines]

        # Apply post-OCR correction rules if specified
        if dto.correctionRules == "akkadian":
            from utils.akkadian_ocr_corrections import correct_lines
            text_lines = correct_lines(text_lines)

        # If image was scaled down, scale bounding box coordinates back up
        if scale < 1.0 and boxes:
            sx = pre_scale_width / image_width
            sy = pre_scale_height / image_height
            boxes = [
                Dimensions(x=int(b.x * sx), y=int(b.y * sy), width=int(b.width * sx), height=int(b.height * sy))
                for b in boxes
            ]

        # If we cropped the image, adjust bounding box coordinates back to original image space
        if crop_offset_x > 0 or crop_offset_y > 0:
            adjusted_boxes = []
            for box in boxes:
                adjusted_boxes.append(Dimensions(
                    x=box.x + crop_offset_x,
                    y=box.y + crop_offset_y,
                    width=box.width,
                    height=box.height
                ))
            boxes = adjusted_boxes
            logging.info(f"Adjusted {len(boxes)} bounding boxes by offset ({crop_offset_x}, {crop_offset_y})")

        # TEI Lex-0 handling
        validation_results = None
        if dto.prompt == "tei_lex0" and text_lines:
            try:
                from services.tei_converter import tei_converter

                if is_tei_two_stage:
                    # ── Two-stage pipeline ──
                    # Stage 2: Convert OCR text → TEI XML using a second model
                    from services.tei_encoding_service import tei_encoding_service

                    ocr_text = result.get("text", "\n".join(text_lines))
                    logging.info(
                        f"TEI Stage 2: encoding {len(ocr_text)} chars with "
                        f"{dto.teiProvider}:{dto.teiModel}"
                    )

                    tei_result = tei_encoding_service.encode_to_tei(
                        ocr_text=ocr_text,
                        model=dto.teiModel,
                        provider=dto.teiProvider or "ollama",
                        api_key=dto.teiApiKey or dto.apiKey,
                    )

                    if tei_result.get("success"):
                        raw_xml = tei_result["text"]
                        logging.info(f"TEI encoding output ({len(raw_xml)} chars): {raw_xml[:500]}...")
                    else:
                        logging.error(f"TEI encoding failed: {tei_result.get('error')}")
                        raw_xml = ""
                else:
                    # ── Single-stage: VLM produced XML directly ──
                    raw_xml = result.get("text", "\n".join(text_lines))
                    logging.info(f"TEI raw output ({len(raw_xml)} chars): {raw_xml[:500]}...")

                # Validate the XML output
                if raw_xml:
                    validated = tei_converter.convert_and_validate(raw_xml)

                    if validated:
                        validation_results = validated
                        text_lines = [entry["xml"] for entry in validated]
                        logging.info(
                            f"TEI validation: {sum(1 for e in validated if e['status'] == 'valid')} valid, "
                            f"{sum(1 for e in validated if e['status'] == 'error')} errors"
                        )
                    else:
                        logging.warning(
                            "TEI mode: No <entry> elements found in output. "
                            "Returning raw OCR lines."
                        )

            except Exception as e:
                logging.error(f"TEI processing failed: {e}")
                import traceback
                traceback.print_exc()

        # Apply box mode override
        box_mode = getattr(dto, 'boxMode', None) or 'estimate'
        if box_mode == 'none':
            boxes = []
        elif box_mode == 'predict' and text_lines:
            try:
                from services.segmentation_service import SegmentationService
                seg_service = SegmentationService()
                seg_result = seg_service.segment(image_base64)
                if seg_result.lines:
                    boxes = seg_result.lines
                    logging.info(f"Segmentation returned {len(boxes)} line boxes (method={seg_result.method})")
            except Exception as e:
                logging.warning(f"Segmentation failed, falling back to estimate: {e}")
        # 'estimate' is the default — uses whatever boxes the OCR model returned
        # (which are typically evenly-divided estimates)

        return CuredResultDto(lines=text_lines, dimensions=boxes, validation_results=validation_results)

    @staticmethod
    def _get_image_dimensions(image_base64: str) -> tuple:
        """Extract width and height from a base64-encoded image."""
        try:
            image_data = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_data))
            return image.size  # (width, height)
        except Exception as e:
            logging.error(f"Failed to get image dimensions: {e}")
            return (1000, 1000)  # fallback

    @staticmethod
    def _crop_to_bounding_box(image_base64: str, bbox: Dimensions) -> tuple:
        """
        Crop the image to the specified bounding box.

        Returns:
            tuple: (cropped_image_base64, x_offset, y_offset)
        """
        try:
            image_data = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_data))
            orig_format = image.format or "PNG"

            # Crop to bounding box (x, y, x+width, y+height)
            left = max(0, bbox.x)
            top = max(0, bbox.y)
            right = min(image.width, bbox.x + bbox.width)
            bottom = min(image.height, bbox.y + bbox.height)

            cropped = image.crop((left, top, right, bottom))

            # Convert back to base64
            buffer = BytesIO()
            cropped.save(buffer, format=orig_format)
            cropped_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            return cropped_base64, left, top
        except Exception as e:
            logging.error(f"Failed to crop image to bounding box: {e}")
            return image_base64, 0, 0

    @staticmethod
    def get_nemotron_status() -> dict:
        """Return current Nemotron configuration and status."""
        return {
            "mode": _nemotron_mode,
            "api_url": _nemotron_client.api_url if _nemotron_mode == "api" else None,
            "model_id": NemotronClient.HF_MODEL_ID if _nemotron_mode == "local" else "nvidia/nemotron-parse",
            "device": _nemotron_client._device if _nemotron_mode == "local" else "cloud",
        }
