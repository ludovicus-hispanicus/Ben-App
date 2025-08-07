from typing import List, Dict

from pydantic import BaseModel

from entities.dimensions import Dimensions
from entities.new_text import TextIdentifier, CureItem, TransliterationSource, TransliterationSubmission
from entities.text import Uploader


class TextIdentifiersDto(BaseModel):
    museum: TextIdentifier = None
    publication: TextIdentifier = None
    p_number: TextIdentifier = None

    def to_query_items(self) -> List[Dict]:
        query_identifiers = []

        if self.p_number is not None:
            query_identifiers.append({"p_number": {"$eq": self.p_number.get_value()}})

        if self.museum:
            query_identifiers.append({"museum_id": {"$eq": self.museum.get_value()}})

        if self.publication:
            query_identifiers.append({"publication_id": {"$eq": self.publication.get_value()}})

        return query_identifiers

    @staticmethod
    def from_values(museum: str = None, p_number: str = None, publication: str = None):
        return TextIdentifiersDto(museum=TextIdentifier.from_value(museum) if museum else None,
                                  p_number=TextIdentifier.from_value(p_number) if p_number else None,
                                  publication=TextIdentifier.from_value(publication) if publication else None)


class SearchTextByIdentifiersDto(BaseModel):
    text_identifiers: TextIdentifiersDto


class BaseSubmissionDto(BaseModel):
    text_id: int = None
    transliteration_id: int = None
    url: str = ""
    is_fixed: bool = False
    uploader: Uploader = Uploader.ADMIN  # recognize this with user id


class TransliterationSubmitDto(BaseSubmissionDto):
    lines: List[str]
    source: TransliterationSource
    boxes: List[Dimensions] = None
    image_name: str = ""
    url: str = ""


class CuredSubmissionDto(BaseModel):
    text_id: int
    lines: List[str]
    boxes: List[Dimensions]
    is_fixed: bool
    image_name: str = None
    transliteration_id: int = None


class CureISubmitDto(BaseSubmissionDto):
    transliteration_id: str
    items: List[List[CureItem]]


class TransliterationSubmissionPreview(BaseModel):
    transliteration_id: int
    uploader_id: str
    last_edited: str
    image_name: str

    @staticmethod
    def from_transliteration_entity(entity: TransliterationSubmission):
        return TransliterationSubmissionPreview(transliteration_id=entity.transliteration_id,
                                                uploader_id=entity.uploader_id,
                                                last_edited=entity.edit_history[-1].time,
                                                image_name=entity.image_name)


class CuredTransliterationData(BaseModel):
    lines: List[str]
    boxes: List[Dimensions]
    is_fixed: bool

    @staticmethod
    def from_transliteration_entity(entity: TransliterationSubmission):
        last = entity.edit_history[-1]
        return CuredTransliterationData(lines=last.lines,
                                        boxes=last.boxes,
                                        is_fixed=last.is_fixed)
