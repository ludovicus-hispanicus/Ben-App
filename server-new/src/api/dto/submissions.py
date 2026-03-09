from typing import List, Dict, Optional

from pydantic import BaseModel

from entities.dimensions import Dimensions
from entities.new_text import TextIdentifier, TransliterationSource, TransliterationSubmission, Uploader


class TextIdentifiersDto(BaseModel):
    museum: Optional[TextIdentifier] = None
    publication: Optional[TextIdentifier] = None
    p_number: Optional[TextIdentifier] = None

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
    text_id: Optional[int] = None
    transliteration_id: Optional[int] = None
    url: str = ""
    is_fixed: bool = False  # legacy
    is_curated_kraken: bool = False
    is_curated_vlm: bool = False
    training_targets: Optional[List[str]] = None  # legacy
    uploader: Uploader = Uploader.ADMIN  # recognize this with user id


class TransliterationSubmitDto(BaseSubmissionDto):
    lines: List[str]
    source: TransliterationSource
    boxes: Optional[List[Dimensions]] = None
    image_name: str = ""
    url: str = ""


class CuredSubmissionDto(BaseModel):
    text_id: int
    lines: List[str]
    boxes: List[Dimensions]
    is_fixed: bool = False  # legacy
    is_curated_kraken: bool = False
    is_curated_vlm: bool = False
    training_targets: Optional[List[str]] = None  # legacy
    image_name: Optional[str] = None
    transliteration_id: Optional[int] = None





class BatchCurateDto(BaseModel):
    text_ids: List[int]
    curate: bool
    target: str = "both"  # "kraken", "vlm", or "both"


class TransliterationSubmissionPreview(BaseModel):
    transliteration_id: int
    uploader_id: str
    last_edited: str
    image_name: str

    @staticmethod
    def from_transliteration_entity(entity: TransliterationSubmission):
        # Guard against empty edit_history
        if not entity.edit_history:
            return None
        return TransliterationSubmissionPreview(transliteration_id=entity.transliteration_id,
                                                uploader_id=entity.uploader_id,
                                                last_edited=entity.edit_history[-1].time,
                                                image_name=entity.image_name)


class CuredTransliterationData(BaseModel):
    lines: List[str]
    boxes: List[Dimensions]
    is_fixed: bool = False  # legacy
    is_curated_kraken: bool = False
    is_curated_vlm: bool = False
    training_targets: Optional[List[str]] = None  # legacy

    @staticmethod
    def from_transliteration_entity(entity: TransliterationSubmission):
        # Guard against empty edit_history
        if not entity.edit_history:
            return None
        last = entity.edit_history[-1]
        # Support legacy data: derive from training_targets/is_fixed if new fields absent
        is_kraken = getattr(last, 'is_curated_kraken', False)
        is_vlm = getattr(last, 'is_curated_vlm', False)
        if not is_kraken and not is_vlm and getattr(last, 'is_fixed', False):
            # Legacy: derive from training_targets
            targets = getattr(last, 'training_targets', None) or []
            is_kraken = 'kraken' in targets
            is_vlm = 'vlm' in targets
            # If is_fixed but no targets, assume both
            if not targets:
                is_kraken = True
                is_vlm = True
        return CuredTransliterationData(
            lines=last.lines,
            boxes=last.boxes or [],
            is_fixed=getattr(last, 'is_fixed', False),
            is_curated_kraken=is_kraken,
            is_curated_vlm=is_vlm,
            training_targets=getattr(last, 'training_targets', None)
        )
