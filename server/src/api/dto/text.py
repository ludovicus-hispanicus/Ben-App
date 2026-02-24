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
    latest_transliteration_id: int = None
    label: str = ""
    part: str = ""
    is_curated: bool = False
    lines_count: int = 0

    # uploader: Uploader = Uploader.ADMIN

    @staticmethod
    def from_new_text(new_text: NewText):
        latest_trans_id = None
        is_curated = False
        lines_count = 0
        if new_text.transliterations:
            latest_trans_id = new_text.transliterations[-1].transliteration_id
            # Get line count from the latest edit of the latest transliteration
            latest_trans = new_text.transliterations[-1]
            if latest_trans.edit_history:
                lines_count = len(latest_trans.edit_history[-1].lines)
            # Check if any transliteration has is_fixed=True in its latest edit
            for trans in new_text.transliterations:
                if trans.edit_history:
                    latest_edit = trans.edit_history[-1]
                    if getattr(latest_edit, 'is_fixed', False):
                        is_curated = True
                        break

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
            uploader_id=new_text.uploader_id,
            latest_transliteration_id=latest_trans_id,
            label=getattr(new_text, 'label', '') or '',
            part=getattr(new_text, 'part', '') or '',
            is_curated=is_curated,
            lines_count=lines_count
        )
