from typing import List, Optional
from random import randint

from api.dto.letter import Letter
from entities.common import PyObjectId
from pydantic import BaseModel, Field, ConfigDict
from bson import ObjectId

from entities.text_progress import TextProgress

from enum import Enum


class Uploader(Enum):
    ADMIN = "admin"
    USER_UPLOAD = "user_upload"


class Text(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        use_enum_values=True,
        populate_by_name=True,
    )

    id: Optional[PyObjectId] = Field(default=None, alias='_id')
    text_id: int
    transliteration: List[List[str]] = None
    original_transliteration: List[str] = []
    metadata: List[dict] = []
    is_in_use: bool = False
    use_start_time: int = -1
    is_fixed: bool = False
    p_number: int = -1
    edit_history: List[TextProgress] = []
    origin: Uploader = Uploader.ADMIN
    uploader_id: str = "admin"

    def get_transliterations(self, label_to_unicode: dict):
        if len(self.edit_history) > 0:
            return self.edit_history[-1].to_transliterations()
        else:
            if not self.transliteration:
                return None

            return [[Letter(letter=letter,
                            symbol=label_to_unicode[letter] if letter in label_to_unicode else "")
                     for letter in line]
                    for line in self.transliteration]

    @staticmethod
    def generate_mock_text():
        return Text(
            text_id=randint(500, 2500),
            transliteration=[["fsd", "fdsfs", "aab"], ["fds", "fdfs", "34a"]],
            metadata=[{"hello": "there"}],
        )
