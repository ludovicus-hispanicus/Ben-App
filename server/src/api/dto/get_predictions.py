from typing import List

from fastapi import UploadFile
from pydantic import EmailStr
from pydantic.main import BaseModel

from api.dto.letter import Letter
from entities.dimensions import Dimensions


class GetPredictionsDto(BaseModel):
    text_id: int = None
    dimensions: List[List[Dimensions]]


class PredictionsDto(BaseModel):
    predictions: List[List[Letter]]
    sign_translation: List[str] = None


class GetStageOneDto(BaseModel):
    requested_text_id: str = None
    old_text_id: str = None


class GetPredictionDto(BaseModel):
    image: str


class CureDGetTransliterationsDto(BaseModel):
    image: str


class AmendmentStats(BaseModel):
    completed_texts: int
    saved_signs: int


class LoginDto(BaseModel):
    email: EmailStr
    password: str


class UserDto(BaseModel):
    name: str
    email: EmailStr
    admin: bool


class UploadImageDto(BaseModel):
    file: UploadFile


class GetSpecificPredictionsDto(BaseModel):
    text_id: int
    dimensions: List[Dimensions]
