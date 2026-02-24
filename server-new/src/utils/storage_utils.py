import logging
import pathlib
import random
from typing import List
from uuid import uuid4

import cv2
import os
import tempfile

from fastapi import UploadFile, HTTPException

from api.dto.submit import ItemDto
from entities.text import Uploader
from common.env_vars import STORAGE_PATH

from PIL import Image

class StorageUtils:
    BASE_PATH = os.environ.get(STORAGE_PATH)
    CURED_TRAINING_DATA_DIR_NAME = "cured_training_data"
    PRODUCTION_IMAGES_DIR_NAME = "production_images"
    PREVIEW_DIR_NAME = "preview"

    def __init__(self):
        pass

    @staticmethod
    def validate_image_file_type(file: UploadFile):
        supported_file_types = ["image/png", "image/jpeg"]
        #, "image/tiff"]
        print(f"-{file.content_type}-")
        if file.content_type not in supported_file_types:
            raise HTTPException(status_code=500, detail=f"File extension {file.content_type} is not supported!")

    @staticmethod
    def get_classes_file_path():
        return os.path.join(StorageUtils.BASE_PATH, "new_sign_to_unicode.csv")

    @staticmethod
    def get_museums_file_path() -> str:
        return os.path.join(StorageUtils.BASE_PATH, "museums.csv")

    @staticmethod
    def save_new_class_to_file(sign: str, symbol: str):
        try:
            logging.info(f"writing {sign} {symbol} to the classes file...")
            classes_file = StorageUtils.get_classes_file_path()
            with open(classes_file, "a+", encoding="utf-8") as classes_file:
                classes_file.write(f"{sign},{symbol}\n")
            logging.info(f"writing {sign} {symbol} to the classes file...DONE")
        except:
            logging.exception("failed to save new sign to file")

    @staticmethod
    def get_text_image_path(text_id: int, origin: Uploader = Uploader.ADMIN):
        if type(text_id) is not int:
            raise HTTPException(status_code=500, detail="Bad text id...")

        if origin == Uploader.USER_UPLOAD or text_id >= 1000000:
            return os.path.join(StorageUtils.BASE_PATH, "user_upload", f"{text_id}.png")
        elif origin == Uploader.ADMIN:
            return os.path.join(StorageUtils.BASE_PATH, "images", f"{text_id}.png")

        return None

    @staticmethod
    def build_preview_image_path(image_name: str) -> str:
        EXT_SUFFIX = ".jpeg"
        if not image_name.endswith(EXT_SUFFIX):
            if "." in image_name:
                image_name = image_name.split(".")[0] + EXT_SUFFIX
            else:
                image_name += EXT_SUFFIX

        return os.path.join(StorageUtils.BASE_PATH, StorageUtils.PREVIEW_DIR_NAME, image_name)


    @staticmethod
    def build_cured_train_image_path(image_name: str) -> str:
        return os.path.join(StorageUtils.BASE_PATH, StorageUtils.CURED_TRAINING_DATA_DIR_NAME, image_name)

    @staticmethod
    def build_production_image_path(production_id: int, image_id: str) -> str:
        """Build path for a production text uploaded image."""
        return os.path.join(
            StorageUtils.BASE_PATH,
            StorageUtils.PRODUCTION_IMAGES_DIR_NAME,
            str(production_id),
            f"{image_id}.png"
        )

    @staticmethod
    def get_confirmed_signs_path():
        return os.path.join(StorageUtils.BASE_PATH, "confirmed_data")

    @staticmethod
    def make_a_preview(image_path: str, preview_path: str):
        im = Image.open(image_path)
        im.thumbnail((250, 250))

        os.makedirs(os.path.dirname(preview_path), exist_ok=True)
        if im.mode != "RGB":
            im = im.convert("RGB")
        im.save(preview_path, format="JPEG")

    @staticmethod
    async def save_uploaded_image(file: UploadFile, path: str):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as new_file:
                new_file.write(await file.read())
        except Exception as e:
            raise HTTPException(status_code=500, detail="Couldn't save uploaded image") from e

    @staticmethod
    def save_sign_image(item: ItemDto, image_crop):
        cert = ""
        if item.certainty == "!":
            cert = "unattested_or_reconstructed"
        elif item.certainty == "?":
            cert = "uncertain"
        elif item.certainty == "#":
            cert = "damaged"
        elif item.certainty == "#?":
            cert = "damaged_and_uncertain"

        dir_path = os.path.join("output", f"{item.symbol}")
        if cert:
            dir_path = os.path.join(dir_path, cert)

        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        image_path = os.path.join(dir_path, f"{str(uuid4())}.png")
        is_success, im_buf_arr = cv2.imencode(".png", image_crop)
        im_buf_arr.tofile(image_path)

    @staticmethod
    def get_image_as_numpy_array(image_path: str):
        return cv2.imread(image_path)

    @staticmethod
    def create_temp_file() -> (str, str):
        logging.info("creating temp file...")
        temp_file_directory = os.path.join(StorageUtils.BASE_PATH, "tmp_upload")

        if not os.path.isdir(temp_file_directory):
            os.mkdir(temp_file_directory)

        temp_file = tempfile.NamedTemporaryFile(dir=temp_file_directory, delete=False)
        filename = temp_file.name.split("\\")[-1]
        final_path = os.path.join(temp_file_directory, filename)
        return temp_file, final_path

    @staticmethod
    def write_to_file(file, content: bytes):
        try:
            file.write(content)
            file.close()
        except:
            logging.exception("failed to write to file")
            raise

    @staticmethod
    def delete_files(files: List[str]):
        for file in files:
            StorageUtils.delete_file(file)

    @staticmethod
    def delete_file(file_path: str):
        try:
            os.unlink(file_path)
            logging.info(f"Deleted file {file_path}")
        except:
            logging.exception(f"Failed to delete file {file_path}")

    @staticmethod
    def generate_cured_train_image_name(original_file_name: str, text_id: int) -> str:
        image_id = random.randint(10000000, 99999999)
        ext = pathlib.Path(original_file_name).suffix

        return f"{text_id}_{image_id}{ext}"