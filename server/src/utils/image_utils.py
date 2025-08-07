import base64
import io

import cv2
import requests
from PIL import Image

import numpy as np


class ImageUtils:

    def __init__(self):
        pass

    @staticmethod
    def from_base64(image_in_base_64: str) -> bytes:
        return base64.urlsafe_b64decode(image_in_base_64.split(",")[1])

    @staticmethod
    def convert_bytes_to_np_img(img_bytes: str):
        np_arr = np.fromstring(img_bytes, np.uint8)
        return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    @staticmethod
    def save_image(image_data_url: str, path: str):
        data = 'data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUAAAhwAAAFoCAYAAAA.......'
        response = requests.get(data)
        with open('image.jpg', 'wb') as f:
            # f.write(response.read())
            pass

    @staticmethod
    def convert_base64_to_np(image_in_base_64: str):
        base64_raw = image_in_base_64.split(",")[1]
        base64_decoded = base64.b64decode(base64_raw)
        image = Image.open(io.BytesIO(base64_decoded))
        np_array_4d = np.array(image)
        np_array_3d = cv2.cvtColor(np_array_4d, cv2.COLOR_BGRA2BGR)
        return np_array_3d


if __name__ == '__main__':
    # img_in_base_64 = input("paste str of img")
    # result = ImageUtils.convert_base64_to_np(img_in_base_64)
    # is_success, im_buf_arr = cv2.imencode(".png", result)
    # im_buf_arr.tofile("./img.png")
    #
    # ok = cv2.imread("./img.png")
    # ai_handler = AIHandler()
    # ai_handler.get_bounding_boxes(np_img=ok)
    #
    # logging.info(f"done -\n {result}")
    pass