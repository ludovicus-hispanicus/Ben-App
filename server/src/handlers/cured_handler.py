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


class CuredHandler:

    # Model name mapping
    MODEL_FILES = {
        "latest": "model.mlmodel",
        "dillard": "dillard.mlmodel",
        "base": "base.mlmodel"
    }

    @staticmethod
    def get_transliterations(dto: CureDGetTransliterationsDto, background_tasks: BackgroundTasks):
        temp_image_path = CuredHandler._save_temp_image(image=dto.image, background_tasks=background_tasks)

        image = Image.open(temp_image_path)
        boxes = CuredHandler.get_text_bounding_boxes(image=image)

        # Get model name from DTO, default to "latest"
        model_name = getattr(dto, 'model', 'latest')
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

        # Get model file from mapping, default to model.mlmodel
        model_file = CuredHandler.MODEL_FILES.get(model_name, "model.mlmodel")
        model_path = f"./cured_models/{model_file}"

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
