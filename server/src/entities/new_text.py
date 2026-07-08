from enum import Enum
from typing import List, Optional, Dict

from entities.common import PyObjectId
from pydantic import BaseModel, Field, ConfigDict
from bson import ObjectId

from entities.dimensions import Dimensions
class Uploader(Enum):
    ADMIN = "admin"
    USER_UPLOAD = "user_upload"


class DbModel(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias='_id')

    def get_id(self) -> PyObjectId:
        return self.id

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        use_enum_values=True,
        populate_by_name=True,
    )


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
        if self.number == 0:
            return self.name
        return f"{self.name}-{self.number}"

    @staticmethod
    def from_value(value: str):
        splitted = value.rsplit("-", maxsplit=1)
        if len(splitted) == 2:
            try:
                return TextIdentifier(name=splitted[0], number=int(splitted[1]))
            except ValueError:
                pass
        return TextIdentifier(name=value, number=0)


class TransliterationEdit(DbModel):
    lines: List[str]
    boxes: Optional[List[Dimensions]] = None
    time: str
    user_id: str
    is_fixed: bool = False  # legacy — kept for backward compat with old data
    is_curated_kraken: bool = False
    is_curated_vlm: bool = False
    is_reviewed: bool = False  # lightweight "I checked the OCR" flag
    training_targets: Optional[List[str]] = None  # legacy
    guides: Optional[List[Dict]] = None  # bezier reading guide lines

    @property
    def is_curated(self) -> bool:
        """True if curated for any target (also checks legacy is_fixed)."""
        return self.is_curated_kraken or self.is_curated_vlm or self.is_fixed


class TransliterationSubmission(DbModel):
    transliteration_id: Optional[int]
    source: TransliterationSource
    edit_history: List[TransliterationEdit]
    uploader_id: str
    image_name: str = ""
    source_url: str = ""

    def is_curated(self) -> bool:
        return any(edit.is_curated for edit in self.edit_history)


class NewText(DbModel):
    text_id: int
    publication_id: Optional[str] = None
    museum_id: Optional[str] = None
    p_number: Optional[str] = None
    transliterations: List[TransliterationSubmission] = []
    metadata: List[Dict] = []
    is_in_use: bool = False
    use_start_time: int = -1
    is_fixed: bool = False  # replace with function?
    uploader: Uploader = Uploader.ADMIN
    uploader_id: str = "admin"
    labels: List[str] = []
    label: str = ""  # Legacy — migrated to labels on read
    part: str = ""
    dataset_id: Optional[int] = None
    # Column (a/b) of the source snippet on its dictionary page. Stamped once
    # from the manifest that was correct at creation/backfill time, so it stays
    # right even if a later snippet re-extraction renumbers the source folder
    # (which decouples the `publication_id` filename from the actual snippet).
    column: Optional[str] = None
    # Page-relative normalized center (0..1) of the source snippet, also stamped
    # from the manifest. `y` gives within-column vertical order so dictionary
    # entries can be assembled from the records alone — sort by (page, column, y)
    # — without re-joining the (renumber-prone) snippet manifest. `x` lets column
    # be re-derived/verified (a if x < 0.5 else b).
    x: Optional[float] = None
    y: Optional[float] = None
    # True snippet class (header/meaning/discussion/bilingualLexical/refEntry/
    # partMeaning/…) from the manifest's class_name. The class encoded in the
    # `publication_id` filename can be wrong (the OCR app and the YOLO detector
    # disagree on some blocks), which misdrives entry merging — so merging should
    # read `block_class`, not the identifier. Stamped like column at OCR time.
    block_class: Optional[str] = None

    @property
    def effective_labels(self) -> List[str]:
        """Return labels list, falling back to legacy label field."""
        if self.labels:
            return self.labels
        if self.label:
            return [self.label]
        return []
