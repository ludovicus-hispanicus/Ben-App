from typing import List, Optional
from pydantic import BaseModel
from enum import Enum


class IdentifierType(str, Enum):
    MUSEUM = "museum"
    P_NUMBER = "p_number"
    PUBLICATION = "publication"


class ProductionEdit(BaseModel):
    """Tracks each edit to the production text."""
    content: str  # The full text content
    time: str  # ISO timestamp
    user_id: str


class SourceTextReference(BaseModel):
    """Reference to a source text from training data."""
    text_id: int
    transliteration_id: int
    part: str  # Part number/identifier
    image_name: str


class UploadedImage(BaseModel):
    """Reference to an uploaded image (copy/photo) for a production text."""
    image_id: str  # Unique identifier for the image
    image_name: str  # Original filename
    label: str  # Display label (e.g., "Copy 1", "Photo 1")
    uploaded_at: str  # ISO timestamp


class ProductionText(BaseModel):
    """
    A curated/production text that merges multiple training data parts.
    This is the scholarly output, separate from OCR training data.
    """
    production_id: int  # Unique ID
    identifier: str  # Museum number, P-number, or Publication ID
    identifier_type: IdentifierType
    source_texts: List[SourceTextReference] = []  # References to source parts
    uploaded_images: List[UploadedImage] = []  # Uploaded images (copies/photos)
    content: str = ""  # The merged/edited transliteration text
    translation_content: str = ""  # The edited translation text
    edit_history: List[ProductionEdit] = []  # Track edits
    created_at: str = ""
    last_modified: str = ""
    uploader_id: str = ""
    notes: str = ""  # Optional scholarly notes
    is_exported: bool = False  # Whether the text has been exported to eBL
