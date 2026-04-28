from typing import List, Dict, Optional

from pydantic import BaseModel


class BatchRecognitionRequest(BaseModel):
    source_project_id: Optional[str] = None  # Library folder (server-managed)
    source_folder_path: Optional[str] = None  # Local filesystem path (direct import)
    include_classes: Optional[List[str]] = None  # Filter images by YOLO class name
    destination_dataset_id: Optional[int] = None  # CuReD dataset (integer ID)
    destination_folder_path: Optional[str] = None  # Export to local folder
    export_images: bool = False  # Copy source images to export folder
    model: str = "nemotron"
    prompt: str = "dictionary"
    custom_prompt: Optional[str] = None  # Raw prompt text (overrides prompt key)
    api_key: Optional[str] = None
    sub_model: Optional[str] = None
    batch_size: int = 1  # Images per VLM inference call (1 = one at a time)
    correction_rules: Optional[str] = None  # Post-OCR correction rules (e.g. "akkadian")
    image_scale: Optional[float] = None  # Image scale factor (0.33, 0.5, 1.0). None = use global setting.
    target_dpi: Optional[int] = None  # Target DPI for resizing (e.g. 300). Overrides image_scale when set.
    include_filenames: Optional[List[str]] = None  # Only process these filenames (for selective batch)
    exclude_filenames: Optional[List[str]] = None  # Skip these filenames (for resuming truncated batches)
    box_mode: Optional[str] = None  # "estimate" (default) or "predict" (Kraken segmentation)
    tiling_mode: Optional[str] = None  # "none", "two_columns", "four_quadrants"


class BatchRecognitionResultItem(BaseModel):
    filename: str
    text_id: int
    transliteration_id: int
    lines_count: int


class BatchRecognitionFailedItem(BaseModel):
    filename: str
    error: str


class VllmStatusResponse(BaseModel):
    available: bool
    models: List[str] = []
    url: str = ""


class BatchRecognitionStatusResponse(BaseModel):
    success: bool
    job_id: str
    status: str  # pending, running, completed, failed, cancelled
    source_project_name: str = ""
    model: str = ""
    prompt: str = ""
    current_image: int = 0
    total_images: int = 0
    processed_images: int = 0
    failed_images: int = 0
    progress_percent: float = 0
    current_filename: str = ""
    results: List[Dict] = []
    failed_results: List[Dict] = []
    error: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
