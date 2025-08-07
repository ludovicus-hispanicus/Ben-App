import logging
import random
from typing import List

from fastapi import UploadFile, File, HTTPException

from api.dto.detectron_settings import DetectronSettings
from api.dto.letter import Letter
from api.dto.stage_one import StageOneDto
from entities.dimensions import Dimensions
from entities.text import Text, Uploader
from common.global_handlers import global_texts_handler, global_ai_handler
from utils.storage_utils import StorageUtils


class CureIHandler:

    def __init__(self):
        pass

    @staticmethod
    async def get_stage_one(detectron_settings: DetectronSettings, requested_text_id=None, old_text_id=None,
                            file: UploadFile = None, user_id: str = None) -> StageOneDto:
        CureIHandler._handle_old_text(old_text_id=old_text_id)
        if file:
            return await CureIHandler._get_stage_one_of_custom_image(file=file, user_id=user_id,
                                                                     detectron_settings=detectron_settings)

        return CureIHandler._get_stage_one_of_text(requested_text_id=requested_text_id,
                                                   detectron_settings=detectron_settings)

    @staticmethod
    def _handle_old_text(old_text_id: str = ""):
        if old_text_id:
            logging.info(f"got old text: {old_text_id}")
            global_texts_handler.set_text_not_in_use(text_id=old_text_id)

    @staticmethod
    async def _get_stage_one_of_custom_image(user_id: str, detectron_settings: DetectronSettings,
                                             file: UploadFile = File(...)) -> StageOneDto:
        logging.info(f"User {user_id} uploading {file.filename}")
        text_id = random.randint(1000000, 9999999)

        path = StorageUtils.get_text_image_path(text_id=text_id, origin=Uploader.USER_UPLOAD)
        await StorageUtils.save_uploaded_image(file=file, path=path)

        preview_path = StorageUtils.build_preview_image_path(image_name=str(text_id))
        StorageUtils.make_a_preview(image_path=path, preview_path=preview_path)

        text = Text(text_id=text_id, origin=Uploader.USER_UPLOAD, uploader_id=user_id)
        global_texts_handler.insert_text(text=text)

        # dimensions = global_ai_handler.get_text_bounding_boxes(text_id=text_id, text_origin=TextOrigin.USER_UPLOAD)
        # return StageOneDto(text_id=text_id, dimensions=dimensions)
        return CureIHandler._get_stage_one_of_text(requested_text_id=str(text_id),
                                                   detectron_settings=detectron_settings)

    @staticmethod
    def _get_stage_one_of_text(detectron_settings: DetectronSettings, requested_text_id: str = "") -> StageOneDto:
        if requested_text_id is not None and requested_text_id != 'null':
            logging.info(f"asked for specific text {requested_text_id}")
            text = global_texts_handler.get_by_text_id(requested_text_id)
        else:
            text = global_texts_handler.get_random_text_to_work_on()

        if not text:
            raise HTTPException(status_code=500, detail="Couldn't find a text.")

        metadata = []
        akkademia = []
        dimensions = None
        label_2_unicode = global_ai_handler.label_to_unicode_old

        transliteration = text.get_transliterations(label_2_unicode)
        if len(text.edit_history) > 0:
            last_edit = text.edit_history[-1]
            dimensions = last_edit.to_dimensions()
            akkademia = last_edit.akkademia
            if text.is_fixed:
                metadata.append({"Text is fixed by": text.edit_history[-1].user_email})
            else:
                metadata.append({"Text saved as work in progress by": text.edit_history[-1].user_email})
        else:
            metadata.append({"is fixed": "No"})

        metadata.append({"Is someone working on it too now": "Maybe" if text.is_in_use else "No"})
        metadata.append({"uploaded by": text.uploader_id})
        metadata.append({"CuReI text id": text.text_id})
        metadata.extend(text.metadata)
        dimensions = dimensions or global_ai_handler.get_text_bounding_boxes(text_id=text.text_id,
                                                                             detectron_settings=detectron_settings,
                                                                             text_origin=Uploader(text.origin))
        return StageOneDto(text_id=text.text_id, transliteration=transliteration,
                           akkademia=akkademia, dimensions=dimensions,
                           metadata=metadata, is_fixed=text.is_fixed)

    @staticmethod
    async def get_predictions_of_text(dimensions: List[List[Dimensions]], text_id: int) -> List[List[Letter]]:
        logging.info(f"get predictions for text {text_id}")
        text = global_texts_handler.get_text(text_id=text_id)
        predictions = global_ai_handler.get_text_predictions(text=text, bounding_boxes=dimensions)
        transliteration = global_texts_handler.get_text(text_id=text_id)\
            .get_transliterations(global_ai_handler.label_to_unicode_new)
        unicode_to_label = global_ai_handler.unicode_to_labels
        if not transliteration:
            return predictions

        for line_index, line in enumerate(predictions):
            for prediction_index, prediction in enumerate(line):
                if prediction.symbol in unicode_to_label:
                    try:
                        if transliteration[line_index][prediction_index] in unicode_to_label[prediction.symbol]:
                            prediction.letter = transliteration[line_index][prediction_index]
                    except:
                        pass
                    finally:
                        if not prediction.letter:
                            prediction.letter = unicode_to_label[prediction.symbol][0]

        return predictions

    @staticmethod
    async def get_specific_predictions_of_text(dimensions: List[List[Dimensions]], text_id: int):
        pass
