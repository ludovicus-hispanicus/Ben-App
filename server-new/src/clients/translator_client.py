from typing import List

import requests
import os

from rich import json

from common.env_vars import TRANSLATOR_URL


class TranslatorClient:
    URL = os.environ.get(TRANSLATOR_URL)

    def __init__(self):
        pass

    @staticmethod
    def translate(text: List[str]) -> List[str]:
        url = "/akkademia/translate"
        res = requests.post(TranslatorClient.URL + url, data={"text": text})
        return json.loads(res.text)
