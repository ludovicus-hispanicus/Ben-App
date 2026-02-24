import pathlib
import random
import logging
from typing import List

from starlette.background import BackgroundTasks

from api.dto.cured_result import CuredResultDto
from api.dto.get_predictions import CureDGetTransliterationsDto
from entities.dimensions import Dimensions
from utils.image_utils import ImageUtils
from utils.storage_utils import StorageUtils
from kraken import binarization, pageseg
from PIL import Image
import os

# Import Akkadian post-processor
try:
    from services.akkadian_post_processor import akkadian_post_processor
    POST_PROCESSOR_AVAILABLE = True
except ImportError:
    POST_PROCESSOR_AVAILABLE = False
    logging.warning("Akkadian post-processor not available")

# Import DeepSeek OCR service (in-process)
try:
    from services import deepseek_ocr_service
    DEEPSEEK_AVAILABLE = deepseek_ocr_service.is_available()
    if DEEPSEEK_AVAILABLE:
        logging.info("DeepSeek-OCR-2 is available (GPU detected)")
    else:
        logging.warning("DeepSeek-OCR-2 not available (no GPU or missing dependencies)")
except ImportError:
    DEEPSEEK_AVAILABLE = False
    deepseek_ocr_service = None
    logging.warning("DeepSeek-OCR-2 service not available")


class CuredHandler:

    # Model name mapping
    MODEL_FILES = {
        "latest": "model.mlmodel",
        "dillard": "dillard.mlmodel",
        "base": "base.mlmodel",
    }

    @staticmethod
    def get_transliterations(dto: CureDGetTransliterationsDto, background_tasks: BackgroundTasks):
        temp_image_path = CuredHandler._save_temp_image(image=dto.image, background_tasks=background_tasks)

        # Get model name from DTO, default to "latest"
        model_name = getattr(dto, 'model', 'latest')

        # Check if using DeepSeek OCR
        if model_name == "deepseek":
            return CuredHandler._get_transliterations_deepseek(
                image_base64=dto.image,
                temp_image_path=temp_image_path,
                background_tasks=background_tasks
            )

        # Standard Kraken-based flow
        image = Image.open(temp_image_path)
        boxes = CuredHandler.get_text_bounding_boxes(image=image)

        text_lines = CuredHandler.get_text_lines_with_ai(text_image_path=temp_image_path,
                                                         background_tasks=background_tasks,
                                                         model_name=model_name)
        text_lines = [line.replace("\n", "") for line in text_lines]

        # Post-processing is now applied manually via the Normalize button in the UI
        # if POST_PROCESSOR_AVAILABLE:
        #     text_lines = akkadian_post_processor.get_corrected_lines(text_lines)
        #     logging.info(f"Applied Akkadian post-processing to {len(text_lines)} lines")

        return CuredResultDto(lines=text_lines, dimensions=boxes)

    @staticmethod
    def _get_transliterations_deepseek(
        image_base64: str,
        temp_image_path: str,
        background_tasks: BackgroundTasks
    ):
        """
        Get transliterations using DeepSeek-OCR-2 (VLM-based OCR).

        Uses Kraken for bounding box detection, then processes each line
        snippet individually with DeepSeek for better accuracy and speed.
        """
        if not DEEPSEEK_AVAILABLE or deepseek_ocr_service is None:
            logging.error("DeepSeek OCR requested but not available, falling back to Kraken")
            # Fallback to default Kraken model
            image = Image.open(temp_image_path)
            boxes = CuredHandler.get_text_bounding_boxes(image=image)
            text_lines = CuredHandler.get_text_lines_with_ai(
                text_image_path=temp_image_path,
                background_tasks=background_tasks,
                model_name="latest"
            )
            text_lines = [line.replace("\n", "") for line in text_lines]
            return CuredResultDto(lines=text_lines, dimensions=boxes)

        logging.info("Using DeepSeek-OCR-2 for text recognition (snippet mode)")

        # Get bounding boxes using Kraken segmentation
        image = Image.open(temp_image_path)
        boxes = CuredHandler.get_text_bounding_boxes(image=image)
        logging.info(f"Kraken detected {len(boxes)} line bounding boxes")

        if len(boxes) == 0:
            logging.warning("No bounding boxes detected by Kraken")
            return CuredResultDto(lines=[], dimensions=[])

        # Process each bounding box snippet individually with DeepSeek
        text_lines = []
        import base64
        from io import BytesIO

        for i, box in enumerate(boxes):
            # Crop the image to this bounding box (with small padding)
            padding = 5
            left = max(0, box.x - padding)
            top = max(0, box.y - padding)
            right = min(image.width, box.x + box.width + padding)
            bottom = min(image.height, box.y + box.height + padding)

            snippet = image.crop((left, top, right, bottom))

            # Convert snippet to base64
            buffer = BytesIO()
            snippet.save(buffer, format="PNG")
            snippet_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            # Run DeepSeek OCR on this snippet
            logging.info(f"Processing snippet {i+1}/{len(boxes)} ({right-left}x{bottom-top}px)")
            result = deepseek_ocr_service.ocr_from_base64(snippet_base64)

            if result["success"] and result["text"].strip():
                # Take just the first line if multiple returned (snippet should be one line)
                line_text = result["lines"][0] if result["lines"] else result["text"].split("\n")[0]
                text_lines.append(line_text.strip())
                logging.info(f"  Snippet {i+1}: '{line_text[:50]}...' ({result['processing_time_ms']}ms)")
            else:
                # Empty or failed - add empty string
                text_lines.append("")
                logging.warning(f"  Snippet {i+1}: OCR failed or empty - {result.get('error', 'no text')}")

        logging.info(f"DeepSeek processed {len(text_lines)} snippets successfully")
        return CuredResultDto(lines=text_lines, dimensions=boxes)

    @staticmethod
    def _save_temp_image(image: str, background_tasks: BackgroundTasks) -> str:
        img = ImageUtils.from_base64(image)

        temp_file, temp_file_path = StorageUtils.create_temp_file()
        try:
            StorageUtils.write_to_file(file=temp_file, content=img)
        finally:
            background_tasks.add_task(StorageUtils.delete_file, temp_file_path)

        return temp_file_path

    @staticmethod
    def get_text_bounding_boxes(image) -> List[Dimensions]:
        bw_im = binarization.nlbin(image)
        seg = pageseg.segment(bw_im, text_direction='horizontal-lr')

        boxes = []
        # Kraken 6.x returns Segmentation object with .lines containing BBoxLine objects
        for line in seg.lines:
            x1, y1, x2, y2 = line.bbox

            x = x1
            width = x2 - x1
            y = y1
            height = y2 - y1
            boxes.append(Dimensions(x=x, y=y, height=height, width=width))

        return boxes

    @staticmethod
    def get_text_lines_with_ai(text_image_path: str, background_tasks: BackgroundTasks, model_name: str = "latest") -> List[str]:
        output_file_path = f"{text_image_path}.txt"

        # Get model file from static mapping first, then check for custom trained models
        model_file = CuredHandler.MODEL_FILES.get(model_name)
        if model_file:
            model_path = f"./cured_models/{model_file}"
        else:
            # Dynamic lookup: check if a .mlmodel file with this name exists
            dynamic_path = f"./cured_models/{model_name}.mlmodel"
            if os.path.exists(dynamic_path):
                model_path = dynamic_path
            else:
                logging.warning(f"Model '{model_name}' not found, falling back to default")
                model_path = f"./cured_models/{CuredHandler.MODEL_FILES['latest']}"

        logging.info(f"Using OCR model: {model_name} -> {model_path}")

        command = f"kraken" \
                  f" -i {text_image_path} {output_file_path}" \
                  f" binarize segment ocr " \
                  f" -m {model_path}"
        try:
            os.system(command)
            with open(output_file_path) as result_file:
                result = result_file.readlines()
        finally:
            background_tasks.add_task(StorageUtils.delete_file, output_file_path)

        return result
