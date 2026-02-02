"""
DTOs for YOLO layout detection training and inference.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class YoloModelSize(str, Enum):
    """YOLO model size variants."""
    NANO = "n"      # YOLOv8n - fastest, least accurate
    SMALL = "s"     # YOLOv8s - good balance
    MEDIUM = "m"    # YOLOv8m - better accuracy
    LARGE = "l"     # YOLOv8l - high accuracy
    XLARGE = "x"    # YOLOv8x - highest accuracy, slowest


class TrainingStatus(str, Enum):
    """Training job status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============== Dataset DTOs ==============

class YoloClass(BaseModel):
    """A class definition for YOLO training."""
    id: int
    name: str


class YoloAnnotation(BaseModel):
    """A single bounding box annotation in YOLO format."""
    class_id: int
    x_center: float = Field(..., ge=0, le=1, description="Normalized x center (0-1)")
    y_center: float = Field(..., ge=0, le=1, description="Normalized y center (0-1)")
    width: float = Field(..., ge=0, le=1, description="Normalized width (0-1)")
    height: float = Field(..., ge=0, le=1, description="Normalized height (0-1)")


class DatasetCreateRequest(BaseModel):
    """Request to create a new YOLO dataset."""
    name: str = Field(..., min_length=1, max_length=100, description="Dataset name (e.g., 'ahw_layout')")
    classes: List[str] = Field(..., min_items=1, description="List of class names")
    description: Optional[str] = None


class DatasetCreateResponse(BaseModel):
    """Response after creating a dataset."""
    success: bool
    dataset_id: str
    name: str
    classes: List[YoloClass]
    message: str


class ImageUploadRequest(BaseModel):
    """Request to upload an image with annotations to a dataset."""
    image: str = Field(..., description="Base64 encoded image")
    filename: str = Field(..., description="Original filename")
    annotations: List[YoloAnnotation] = Field(default=[], description="Bounding box annotations")
    split: str = Field(default="train", description="Dataset split: 'train' or 'val'")


class ImageUploadResponse(BaseModel):
    """Response after uploading an image."""
    success: bool
    image_id: str
    filename: str
    annotation_count: int
    message: str


class DatasetStatsResponse(BaseModel):
    """Statistics about a dataset."""
    dataset_id: str
    name: str
    classes: List[YoloClass]
    total_images: int
    train_images: int
    val_images: int
    total_annotations: int
    class_distribution: Dict[str, int]
    ready_for_training: bool
    issues: List[str]


class DatasetListItem(BaseModel):
    """Summary info for dataset listing."""
    dataset_id: str
    name: str
    class_count: int
    image_count: int
    created_at: datetime
    updated_at: datetime


# ============== Model DTOs ==============

class ModelInfo(BaseModel):
    """Information about a trained YOLO model."""
    model_id: str
    name: str
    base_model: str
    dataset_name: str
    classes: List[YoloClass]
    metrics: Optional[Dict[str, float]] = None  # mAP50, mAP50-95, precision, recall
    created_at: datetime
    training_epochs: int
    file_path: str
    file_size_mb: float


class ModelListResponse(BaseModel):
    """Response listing available models."""
    success: bool
    models: List[ModelInfo]
    base_models: List[str]  # Available base models (yolov8n, yolov8s, etc.)


# ============== Training DTOs ==============

class TrainingConfig(BaseModel):
    """Configuration for YOLO training."""
    epochs: int = Field(default=100, ge=1, le=1000, description="Number of training epochs")
    batch_size: int = Field(default=4, ge=1, le=64, description="Batch size")
    image_size: int = Field(default=1024, ge=320, le=1920, description="Training image size")
    patience: int = Field(default=20, ge=5, le=100, description="Early stopping patience")
    device: str = Field(default="auto", description="Device: 'auto', 'cpu', '0', '0,1'")
    workers: int = Field(default=4, ge=0, le=16, description="Data loader workers")
    # Augmentation settings (disabled by default for documents)
    flipud: float = Field(default=0.0, ge=0, le=1, description="Vertical flip probability")
    fliplr: float = Field(default=0.0, ge=0, le=1, description="Horizontal flip probability")
    mosaic: float = Field(default=0.0, ge=0, le=1, description="Mosaic augmentation probability")


class TrainingStartRequest(BaseModel):
    """Request to start a training job."""
    dataset_name: str = Field(..., description="Name of the dataset to train on")
    base_model: str = Field(default="yolov8s.pt", description="Base model to fine-tune")
    output_name: str = Field(..., description="Name for the trained model (e.g., 'ahw_layout_v2')")
    config: TrainingConfig = Field(default_factory=TrainingConfig)


class TrainingStartResponse(BaseModel):
    """Response after starting training."""
    success: bool
    training_id: str
    message: str
    estimated_time: Optional[str] = None


class TrainingProgress(BaseModel):
    """Current training progress."""
    training_id: str
    status: TrainingStatus
    current_epoch: int
    total_epochs: int
    progress_percent: float
    metrics: Optional[Dict[str, float]] = None  # Current metrics
    eta_seconds: Optional[int] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TrainingStatusResponse(BaseModel):
    """Response for training status query."""
    success: bool
    progress: TrainingProgress


# ============== Inference DTOs ==============

class BoundingBox(BaseModel):
    """A detected bounding box."""
    x: float = Field(..., description="Left x coordinate (pixels)")
    y: float = Field(..., description="Top y coordinate (pixels)")
    width: float = Field(..., description="Box width (pixels)")
    height: float = Field(..., description="Box height (pixels)")


class Detection(BaseModel):
    """A single detection result."""
    class_id: int
    class_name: str
    confidence: float = Field(..., ge=0, le=1)
    bbox: BoundingBox


class PredictRequest(BaseModel):
    """Request to run inference on an image."""
    image: str = Field(..., description="Base64 encoded image")
    model: str = Field(default="default", description="Model name or 'default'")
    confidence: float = Field(default=0.25, ge=0.01, le=1.0, description="Confidence threshold")
    iou: float = Field(default=0.45, ge=0.1, le=1.0, description="IoU threshold for NMS")


class PredictResponse(BaseModel):
    """Response from inference."""
    success: bool
    detections: List[Detection]
    model_used: str
    processing_time_ms: int
    image_size: Dict[str, int]  # {"width": ..., "height": ...}
    error: Optional[str] = None


# ============== Combined Layout+OCR DTOs ==============

class ProcessPageRequest(BaseModel):
    """Request to process a page with layout detection + OCR."""
    image: str = Field(..., description="Base64 encoded image")
    layout_model: str = Field(default="default", description="YOLO model for layout detection")
    ocr_model: str = Field(default="default", description="Kraken model for OCR")
    confidence: float = Field(default=0.25, ge=0.01, le=1.0)
    run_ocr: bool = Field(default=True, description="Whether to run OCR on detected regions")


class ProcessedRegion(BaseModel):
    """A detected region with optional OCR text."""
    class_id: int
    class_name: str
    confidence: float
    bbox: BoundingBox
    text: Optional[str] = None
    ocr_confidence: Optional[float] = None


class ProcessPageResponse(BaseModel):
    """Response from full page processing."""
    success: bool
    regions: List[ProcessedRegion]
    layout_model: str
    ocr_model: Optional[str] = None
    processing_time_ms: int
    error: Optional[str] = None
