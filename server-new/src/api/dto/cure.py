"""
CuRe DTOs — Request and response models for CuRe sign classification API.
"""
from typing import List, Optional

from pydantic import BaseModel

from entities.dimensions import Dimensions


class CuReClassifyRequest(BaseModel):
    image: str  # base64 encoded image
    model: str = "active"  # model name or "active"


class CuReGuess(BaseModel):
    label: str
    unicode: str
    confidence: float


class CuReSignResult(BaseModel):
    label: str
    unicode: str
    confidence: float
    line: int
    position: int
    bbox: Dimensions
    top3: List[CuReGuess]


class CuReClassifyResponse(BaseModel):
    lines: List[str]  # space-separated sign labels per line
    dimensions: List[Dimensions]  # per-sign bounding boxes
    signs: List[CuReSignResult]  # detailed sign-level results


class CuReDetectRequest(BaseModel):
    image: str  # base64 encoded image


class CuReDetectResponse(BaseModel):
    dimensions: List[Dimensions]
    line_count: int
    sign_count: int


class CuReCropClassifyRequest(BaseModel):
    image: str  # base64 encoded 64x64 crop
    model: str = "active"
    top_k: int = 3


class CuReCropClassifyResponse(BaseModel):
    predictions: List[CuReGuess]


class CuReTrainingStartRequest(BaseModel):
    epochs: int = 50
    model_name: Optional[str] = None
    batch_size: int = 256
    learning_rate: float = 0.001
    base_model: Optional[str] = None  # start from existing model


class CuReAnnotationUploadRequest(BaseModel):
    image: str  # base64 encoded full tablet image
    annotations_csv: str  # CSV content: x1,y1,x2,y2,label per sign
    image_name: Optional[str] = None


class CuReLabelUploadRequest(BaseModel):
    csv_content: str  # CSV content with label,unicode columns
