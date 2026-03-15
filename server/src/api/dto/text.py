import base64
import os.path
from datetime import datetime
from typing import List, Dict, Optional

from pydantic import BaseModel

from api.dto.submissions import TextIdentifiersDto
from entities.new_text import NewText

from utils.storage_utils import StorageUtils


class CreateTextDto(BaseModel):
    text_identifiers: TextIdentifiersDto
    metadata: List[Dict] = []
    dataset_id: Optional[int] = None


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
    latest_transliteration_id: Optional[int] = None
    labels: List[str] = []
    label: str = ""  # Legacy compat
    part: str = ""
    is_curated: bool = False
    is_curated_kraken: bool = False
    is_curated_vlm: bool = False
    lines_count: int = 0
    dataset_id: Optional[int] = None
    image_size: Optional[int] = None  # file size in bytes

    @staticmethod
    def from_new_text(new_text: NewText):
        latest_trans_id = None
        is_curated_kraken = False
        is_curated_vlm = False
        lines_count = 0
        if new_text.transliterations:
            latest_trans_id = new_text.transliterations[-1].transliteration_id
            latest_trans = new_text.transliterations[-1]
            if latest_trans.edit_history:
                lines_count = len(latest_trans.edit_history[-1].lines)
            # Check curation status from latest edit of each transliteration
            for trans in new_text.transliterations:
                if trans.edit_history:
                    latest_edit = trans.edit_history[-1]
                    # New fields
                    if getattr(latest_edit, 'is_curated_kraken', False):
                        is_curated_kraken = True
                    if getattr(latest_edit, 'is_curated_vlm', False):
                        is_curated_vlm = True
                    # Legacy: derive from is_fixed + training_targets
                    if not is_curated_kraken and not is_curated_vlm and getattr(latest_edit, 'is_fixed', False):
                        targets = getattr(latest_edit, 'training_targets', None) or []
                        if 'kraken' in targets:
                            is_curated_kraken = True
                        if 'vlm' in targets:
                            is_curated_vlm = True
                        if not targets:
                            is_curated_kraken = True
                            is_curated_vlm = True

        is_curated = is_curated_kraken or is_curated_vlm

        # Get image file size from the latest transliteration's image
        image_size = None
        try:
            image_name = None
            if new_text.transliterations:
                image_name = new_text.transliterations[-1].image_name
            if image_name:
                img_path = StorageUtils.build_cured_train_image_path(image_name)
                if not os.path.isfile(img_path):
                    img_path = StorageUtils.build_preview_image_path(image_name)
                if os.path.isfile(img_path):
                    image_size = os.path.getsize(img_path)
        except Exception:
            pass

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
            labels=new_text.effective_labels,
            label=new_text.effective_labels[0] if new_text.effective_labels else '',
            part=getattr(new_text, 'part', '') or '',
            is_curated=is_curated,
            is_curated_kraken=is_curated_kraken,
            is_curated_vlm=is_curated_vlm,
            lines_count=lines_count,
            dataset_id=getattr(new_text, 'dataset_id', None),
            image_size=image_size,
        )
