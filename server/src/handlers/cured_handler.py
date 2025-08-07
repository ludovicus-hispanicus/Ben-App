import pathlib
import random
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


class CuredHandler:

    @staticmethod
    def get_transliterations(dto: CureDGetTransliterationsDto, background_tasks: BackgroundTasks):
        temp_image_path = CuredHandler._save_temp_image(image=dto.image, background_tasks=background_tasks)

        image = Image.open(temp_image_path)
        boxes = CuredHandler.get_text_bounding_boxes(image=image)

        text_lines = CuredHandler.get_text_lines_with_ai(text_image_path=temp_image_path,
                                                         background_tasks=background_tasks)
        text_lines = [line.replace("\n", "") for line in text_lines]

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
        for box in seg['boxes']:
            x1 = box[0]
            y1 = box[1]
            x2 = box[2]
            y2 = box[3]

            x = x1
            width = x2 - x1
            y = y1
            height = y2 - y1
            boxes.append(Dimensions(x=x, y=y, height=height, width=width))

        return boxes

    @staticmethod
    def get_text_lines_with_ai(text_image_path: str, background_tasks: BackgroundTasks) -> List[str]:
        output_file_path = f"{text_image_path}.txt"
        command = f"kraken" \
                  f" -i {text_image_path} {output_file_path}" \
                  f" binarize segment ocr " \
                  f" -m ./cured_models/model.mlmodel"
        try:
            os.system(command)
            with open(output_file_path) as result_file:
                result = result_file.readlines()
        finally:
            background_tasks.add_task(StorageUtils.delete_file, output_file_path)

        return result
