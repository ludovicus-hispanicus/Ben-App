import base64
import os.path
from datetime import datetime
from typing import List, Dict

from pydantic import BaseModel

from api.dto.submissions import TextIdentifiersDto
from entities.new_text import NewText
from entities.text import Text
from utils.storage_utils import StorageUtils


class CreateTextDto(BaseModel):
    text_identifiers: TextIdentifiersDto
    metadata: List[Dict] = []


class IdentifiersCollections(BaseModel):
    museums: Dict
    publications: Dict


class GalleryItemDto(BaseModel):
    text_id: int
    transliteration_id: int
    text_identifiers: TextIdentifiersDto
    metadata: List[Dict] = []
    uploader_id: str
    image_base64: str

    @staticmethod
    def from_text(text: Text):
        image_name = str(text.text_id)
        with open(StorageUtils.build_preview_image_path(image_name=image_name), "rb") as f:
            image_base64 = base64.b64encode(f.read())

        return GalleryItemDto(text_id=image_name,
                              transliteration_id=image_name,
                              text_identifiers=TextIdentifiersDto.from_values(museum=None,
                                                                              p_number=str(text.p_number),
                                                                              publication=None),
                              metadata=text.metadata,
                              uploader_id=text.uploader_id,
                              image_base64=image_base64)

    @staticmethod
    def from_new_text(new_text: NewText):
        transliteration = new_text.transliterations[0]
        image_name = transliteration.image_name
        with open(StorageUtils.build_preview_image_path(image_name=image_name), "rb") as f:
            image_base64 = base64.b64encode(f.read())

        return GalleryItemDto(text_id=str(new_text.text_id),
                              transliteration_id=transliteration.transliteration_id,
                              text_identifiers=TextIdentifiersDto.from_values(museum=new_text.museum_id,
                                                                              p_number=new_text.p_number,
                                                                              publication=new_text.publication_id),
                              metadata=new_text.metadata,
                              uploader_id=new_text.uploader_id,
                              image_base64=image_base64)


class NewTextPreviewDto(BaseModel):
    text_id: int
    text_identifiers: TextIdentifiersDto
    transliterations_amount: int
    metadata: List[Dict] = []
    last_modified: str
    uploader_id: str

    # uploader: Uploader = Uploader.ADMIN

    @staticmethod
    def from_new_text(new_text: NewText):
        return NewTextPreviewDto(
            text_id=new_text.text_id,
            text_identifiers=TextIdentifiersDto.from_values(
                museum=new_text.museum_id,
                p_number=new_text.p_number,
                publication=new_text.publication_id
            ),
            transliterations_amount=len(new_text.transliterations),
            metadata=new_text.metadata,
            last_modified=str(datetime.fromtimestamp(new_text.use_start_time)),
            uploader_id=new_text.uploader_id
        )
