from enum import Enum
from typing import List, Optional, Dict

from entities.common import PyObjectId
from pydantic import BaseModel, Field
from bson import ObjectId

from entities.dimensions import Dimensions
from entities.text import Uploader


class DbModel(BaseModel):
    _id: Optional[PyObjectId] = Field(alias='_id')

    def get_id(self) -> PyObjectId:
        return self._id

    class Config:
        arbitrary_types_allowed = True
        use_enum_values = True  # <--
        json_encoders = {
            ObjectId: str
        }


class TextIdentifierType(Enum):
    MUSEUM = "museum"
    PUBLICATION = "publication"
    P_NUMBER = "p_number"


class TransliterationSource(Enum):
    URL = "url"
    CURED = "cured"
    AKKADEMIA = "akkademia"


class TextIdentifier(BaseModel):
    name: str
    number: int

    def get_value(self):
        return f"{self.name}-{self.number}"

    @staticmethod
    def from_value(value: str):
        splitted = value.rsplit("-", maxsplit=1)
        return TextIdentifier(name=splitted[0], number=int(splitted[1]))


class TransliterationEdit(DbModel):
    lines: List[str]
    boxes: List[Dimensions] = None
    time: str
    user_id: str
    is_fixed: bool = False


class TransliterationSubmission(DbModel):
    transliteration_id: Optional[int]
    source: TransliterationSource
    edit_history: List[TransliterationEdit]
    uploader_id: str
    image_name: str = ""
    source_url: str = ""

    def is_fixed(self) -> bool:
        return any(edit.is_fixed for edit in self.edit_history)


class CureItem(BaseModel):
    unicode_glyph: str = ""
    sign: str = ""
    dimensions: Dimensions = None
    certainty: str = ""


class CureIEdit(DbModel):
    transliteration_id: str
    items: List[List[CureItem]]
    time: str
    user_email: str


class CureISubmission(DbModel):
    submitter: Uploader
    is_fixed: bool
    edit_history: List[CureIEdit]


class NewText(DbModel):
    text_id: int
    publication_id: str = None
    museum_id: str = None
    p_number: str = None
    transliterations: List[TransliterationSubmission] = []
    cure_submissions: List[CureISubmission] = []
    metadata: List[Dict] = []
    is_in_use: bool = False
    use_start_time: int = -1
    is_fixed: bool = False  # replace with function?
    uploader: Uploader = Uploader.ADMIN
    uploader_id: str = "admin"
    label: str = ""
    part: str = ""
