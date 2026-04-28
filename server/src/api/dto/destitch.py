"""DTOs for destitch endpoints (split / classify / batch)."""

from typing import List, Optional

from pydantic import BaseModel


class DestitchSplitRequest(BaseModel):
    image: str  # base64 encoded image (with or without data URI prefix)
    include_crops: bool = False
    include_masks: bool = False


class DestitchSplitByPathRequest(BaseModel):
    path: str  # absolute filesystem path to a stitched composite
    include_crops: bool = True
    include_masks: bool = False


class DestitchClassifyRequest(BaseModel):
    image: str


class DestitchBatchStartRequest(BaseModel):
    source_folder_path: str
    destination_folder_path: str
    passthrough_non_composites: bool = True
    include_masks: bool = False
    overwrite_existing: bool = False
    include_filenames: Optional[List[str]] = None
    exclude_filenames: Optional[List[str]] = None
