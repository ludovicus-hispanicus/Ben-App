from typing import List, Optional

from fastapi import UploadFile
from pydantic import EmailStr, BaseModel

from api.dto.letter import Letter
from entities.dimensions import Dimensions





class GetPredictionDto(BaseModel):
    image: str


class CureDGetTransliterationsDto(BaseModel):
    image: str
    model: str = "nemotron"  # "nemotron", "gemini", or "openai"
    apiKey: str = None       # Optional API key for the selected provider
    # Optional bounding box to crop image before OCR (for memory-constrained local models)
    boundingBox: Dimensions = None
    # OCR prompt mode: "plain", "markdown", "dictionary", or "tei_lex0"
    prompt: str = "dictionary"
    # Two-stage TEI pipeline: model + provider for the XML encoding step (stage 2)
    # When prompt="tei_lex0", OCR uses "dictionary" prompt, then teiModel converts text→XML
    teiModel: Optional[str] = None       # e.g. "qwen3:8b", "gemini-2.0-flash", "claude-haiku-4-5-20251001"
    teiProvider: Optional[str] = None    # "ollama", "gemini", "openai", "anthropic"
    teiApiKey: Optional[str] = None      # API key for TEI encoding (if different from OCR provider)
    # Post-OCR correction rules applied before returning text (e.g. "akkadian")
    correctionRules: Optional[str] = None
    # Line detection mode: "none", "estimate" (default), or "predict" (Kraken segmentation)
    boxMode: Optional[str] = None





class LoginDto(BaseModel):
    email: EmailStr
    password: str


class UserDto(BaseModel):
    name: str
    email: EmailStr
    admin: bool


class UploadImageDto(BaseModel):
    file: UploadFile



