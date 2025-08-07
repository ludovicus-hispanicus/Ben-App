import logging
from distutils.util import strtobool
from typing import List

import numpy as np
import pandas as pd
import os

from OCR.AnnotationAndPrediction import AnnotationAndPrediction
from api.dto.detectron_settings import DetectronSettings
from common.env_vars import USE_DETECTRON
from api.dto.index import Index
from api.dto.letter import Letter, AIGuess
from api.dto.submit import SubmitDto
from entities.dimensions import Dimensions
from entities.text import Uploader, Text
from utils.storage_utils import StorageUtils


class AIHandler:

    def __init__(self):
        # logging.info("========== initalize ai handler =========")
        print("========== initalize ai handler =========")
        self.ai = AnnotationAndPrediction(model_path='./OCR/cyrus_classifier_with_shai_data_ver3.pt',
                                          detectron2_path='./OCR/Detectron2model.pth',
                                          labels_csv='./OCR/filtered_label_from_Avital_ver3.csv',
                                          unicode_to_label_dict='./OCR/unicode_to_label_dict.csv',
                                          label_to_unicode_dict='./OCR/label_to_unicode_dict.csv')
        self.unicode_to_labels = None
        self.label_to_unicode_old = None
        self._label_to_unicode_new = None
        self._init_dicts()
        self._use_detectron = strtobool(os.environ.get(USE_DETECTRON))

    def _init_dicts(self):
        self.label_to_unicode_old = self.ai.label_to_unicode_dict
        self.label_to_unicode_new: dict = {}

        # init label to unicode from new file
        with open(StorageUtils.get_classes_file_path(), encoding="utf-8") as new_csv:
            for line in new_csv.readlines():
                items = line.split(",")
                sign = items[0]
                unicode = items[1].replace("\n", "")
                self.label_to_unicode_new[sign] = unicode

        self.label_to_unicode_new.update(self.label_to_unicode_old)
        self._fix_label_to_unicode_dict()

        # init unicode to label from label_to_unicode_new
        self.unicode_to_labels = {}
        for label in self.label_to_unicode_new:
            unicode = self.label_to_unicode_new[label]
            if unicode in self.unicode_to_labels:
                self.unicode_to_labels[unicode].append(label)
            else:
                self.unicode_to_labels[unicode] = [label]

    def _fix_label_to_unicode_dict(self):
        try:
            for i in range(1, 6):
                self.label_to_unicode_old[f".{i}"] = f"0.{i}"
        except:
            pass

    def get_text_bounding_boxes(self, text_id: int, detectron_settings: DetectronSettings,
                                text_origin: Uploader = Uploader.ADMIN) -> List[List[Dimensions]]:
        image_path = StorageUtils.get_text_image_path(text_id=text_id, origin=text_origin)
        img_array = StorageUtils.get_image_as_numpy_array(image_path)

        return self.get_bounding_boxes(np_img=img_array, detectron_settings=detectron_settings)

    def get_bounding_boxes(self, np_img: np.ndarray, detectron_settings: DetectronSettings) -> List[List[Dimensions]]:
        try:
            bounding_boxes = self.ai.get_boundingBox_of_img(
                img=np_img, use_detectron=detectron_settings.use_detectron,
                detectron_th=detectron_settings.detectron_sensitivity).values.tolist()
        except Exception as e:
            logging.exception("AI couldn't get bounding boxes for this...")
            return []
        lines = [[]]
        index = 0

        for box in bounding_boxes:
            x, y, width, height, line = box[0], box[1], box[2], box[3], box[4]
            line = line - 1  # lets start from 0 ...
            if line != index:
                index += 1
                lines.append([])
            lines[index].append(Dimensions(x=x, y=y, width=width, height=height))

        return lines

    def get_text_predictions(self, text: Text, bounding_boxes: List[List[Dimensions]]) -> List[List[Letter]]:
        image_path = StorageUtils.get_text_image_path(text_id=text.text_id, origin=Uploader(text.origin))
        img_array = StorageUtils.get_image_as_numpy_array(image_path)
        return self.get_predictions(np_img=img_array, bounding_boxes=bounding_boxes)

    def get_predictions(self, np_img: np.ndarray, bounding_boxes: List[List[Dimensions]]) -> List[List[Letter]]:
        bounding_boxes_df = self._bounding_boxes_matrix_to_data_frame(bounding_boxes=bounding_boxes)
        predictions = self.ai.get_image_prediction(image=np_img, bb_csv=bounding_boxes_df).values.tolist()

        result = [[]]
        index = 0
        for prediction in predictions:
            line_index = prediction[4] - 1
            unicode = prediction[5]
            if line_index != index:
                index += 1
                result.append([])
            result[index].append(Letter(symbol=unicode))

        return result

    def get_text_specific_predictions(self, text: Text,
                                      bounding_boxes: List[Dimensions]) -> List[List[AIGuess]]:
        image_path = StorageUtils.get_text_image_path(text_id=text.text_id,
                                                      origin=Uploader(text.origin))
        img_array = StorageUtils.get_image_as_numpy_array(image_path)
        result = []

        for b_boxes in bounding_boxes:
            y = int(b_boxes.y)
            x = int(b_boxes.x)
            h = int(b_boxes.height)
            w = int(b_boxes.width)
            image_crop = img_array[y:y + h, x:x + w]
            result.append(self.get_detexify_predictions(np_img=image_crop, index=b_boxes.index))

        return result

    def get_detexify_predictions(self, np_img: np.ndarray, index: Index = None) -> List[AIGuess]:
        results = []
        try:
            results = self.ai.get_detexify_prediction(image=np_img)
        except:
            logging.info("ai couldn't detexify")
        guesses = []
        for result in results:
            try:
                guesses.append(AIGuess(
                    letter=Letter(letter=self.unicode_to_labels[result[0]][0], symbol=result[0], index=index),
                    all_letters=", ".join(self.unicode_to_labels[result[0]]),
                    probability=result[1],
                    index=index))
            except:
                logging.error(f"failed to create guess object for result {result}")
        return guesses

    def process_submit_result(self, submit_dto: SubmitDto):
        for item_list in submit_dto.items:
            for item in item_list:
                if item.letter not in self.label_to_unicode_new:
                    self.save_sign_in_memory(sign=item.letter, symbol=item.symbol)
                    StorageUtils.save_new_class_to_file(sign=item.letter, symbol=item.symbol)

    def save_sign_in_memory(self, sign: str, symbol: str):
        self.label_to_unicode_new[sign] = symbol
        if symbol in self.unicode_to_labels:
            self.unicode_to_labels[symbol].append(sign)
        else:
            self.unicode_to_labels[symbol] = [sign]

    @staticmethod
    def _bounding_boxes_matrix_to_data_frame(bounding_boxes: List[List[Dimensions]]) -> pd.DataFrame:
        data = {
            "X": [int(box.x) for line in bounding_boxes for box in line],
            "Y": [int(box.y) for line in bounding_boxes for box in line],
            "WIDTH": [int(box.width) for line in bounding_boxes for box in line],
            "HEIGHT": [int(box.height) for line in bounding_boxes for box in line],
            "LINE": [index + 1 for index, line in enumerate(bounding_boxes) for _ in line]
        }

        return pd.DataFrame(data, columns=['X', 'Y', 'WIDTH', 'HEIGHT', "LINE"])

    @staticmethod
    def _bounding_boxes_list_to_data_frame(bounding_boxes: List[Dimensions]) -> pd.DataFrame:
        data = {
            "X": [int(box.x) for box in bounding_boxes],
            "Y": [int(box.y) for box in bounding_boxes],
            "WIDTH": [int(box.width) for box in bounding_boxes],
            "HEIGHT": [int(box.height) for box in bounding_boxes],
            "INDEX": [index for index, _ in enumerate(bounding_boxes)]
        }

        return pd.DataFrame(data, columns=['X', 'Y', 'WIDTH', 'HEIGHT', "INDEX"])

    # if __name__ == '__main__':
    # pass
    # with open('ogsl-sl.json', newline='', encoding='utf-8') as f:
    #     data = json.load(f)
    #     final_result = {}
    #     good = 0
    #     bad = {}
    #     signs = data["signs"]
    #     for sign in signs:
    #         sign_data = signs[sign]
    #         if "utf8" in sign_data:
    #             unicode = sign_data["utf8"]
    #             if "values" in sign_data:
    #                 calls = sign_data["values"]
    #                 for call in calls:
    #                     final_result[call] = unicode
    #                 good += 1
    #         else:
    #             bad[sign] = sign_data
    #             # print(sign_data)
    #
    #     print(bad)
    #     with open('avital.json', 'w') as outfile:
    #         json.dump(bad, outfile)
    #     # print("good ", good)
    #     # print("bad ", bad)
    #     # with open("new_sign_to_unicode.csv", "w", encoding="utf-8", ) as new_file:
    #     #     for label in final_result:
    #     #         new_file.write(f"{label},{final_result[label]}\n")
    #
    #     # print(final_result)
    #
    #     # for key in label_to_unicode_dict:
    #     #     l: str = label_to_unicode_dict[key]
    #     #     print(l)
    #     #     l = l.replace("|", "")
    #     #     l = l.replace("\\", "")
    #     #     l = l.replace("'", "")
    #     #     signs = l.split(" ")
    #     #     print(signs)
