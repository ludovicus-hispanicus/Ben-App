from typing import List, Optional

# Auth removed for desktop app
# from auth.auth_bearer import JWTBearer

from api.dto.submissions import SearchTextByIdentifiersDto
from api.dto.text import CreateTextDto, NewTextPreviewDto
from common.global_handlers import global_new_text_handler
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
import logging


class UpdateLabelDto(BaseModel):
    label: str = ""


class UpdateLabelsDto(BaseModel):
    labels: List[str] = []


class UpdatePartDto(BaseModel):
    part: str = ""


class UpdateIdentifiersDto(BaseModel):
    museum_id: Optional[str] = None
    p_number: Optional[str] = None
    publication_id: Optional[str] = None

router = APIRouter(
    prefix="/api/v1/text",
    tags=["items"],
    responses={404: {"description": "Not found"}}
)


@router.get("/list")
async def list_texts() -> List[NewTextPreviewDto]:
    return global_new_text_handler.list_texts()


@router.get("/labels")
async def get_labels() -> List[str]:
    return global_new_text_handler.get_all_labels()


@router.get("/parts-by-identifier")
async def get_parts_by_identifier(identifier: str = "") -> List[int]:
    return global_new_text_handler.get_parts_by_identifier(identifier)


@router.get("/museums")
async def get_identifiers_collections():
    # return IdentifiersCollections(museums=global_new_text_handler.museums,
    #                               publications={})
    return global_new_text_handler.museums


@router.get("/{ben_id}")
async def get_text_by_ben_id(ben_id: int):
    if type(ben_id) is not int:
        raise HTTPException(status_code=500, detail="invalid BEN id")

    return global_new_text_handler.get_by_text_id(ben_id)


@router.get("/isExists/{ben_id}")
async def is_text_exists(ben_id: int):
    if type(ben_id) is not int:
        raise HTTPException(status_code=500, detail="Invalid BEN-id")

    text = global_new_text_handler.get_by_text_id(ben_id)
    logging.info(text)
    return text is not None


@router.post("/textByIdentifiers")
async def get_text_id_by_identifiers(dto: SearchTextByIdentifiersDto):
    logging.info(f"search text {dto}")

    text = global_new_text_handler.get_by_text_identifiers_dto(text_identifiers=dto.text_identifiers)
    logging.info(f"search result: {text.text_id if text else 'None'}")

    return text.text_id if text else -1


@router.get("/textBySymbol/{symbol}")
async def get_text_ids_by_symbol(symbol: str) -> List[NewTextPreviewDto]:
    logging.info(f"search text by symbol {symbol}")

    return global_new_text_handler.get_by_symbol(symbol=symbol)


@router.get("/getRandomTexts/")
async def get_random_texts() -> List[NewTextPreviewDto]:
    return global_new_text_handler.get_random_texts()

# 1. if its new text, create entry using the identifiers and maybe more data - done
# 1.5 - add metadata :(
# 2. then get text-id, with that add transliteration submission
# 3. make sure to include image id of the cured transliteration inside that very object


@router.post("/create")
async def create(request: Request, dto: CreateTextDto) -> int:
    user_id = request.state.user_id

    text_id = global_new_text_handler.create_new_text(
        identifiers=dto.text_identifiers,
        metadata=dto.metadata,
        uploader_id=user_id,
        dataset_id=dto.dataset_id
    )

    return text_id


@router.patch("/{text_id}/label")
async def update_label(text_id: int, dto: UpdateLabelDto):
    if type(text_id) is not int:
        raise HTTPException(status_code=400, detail="invalid BEN id")
    global_new_text_handler.update_label(text_id=text_id, label=dto.label)
    return {"updated": True}


@router.patch("/{text_id}/labels")
async def update_labels(text_id: int, dto: UpdateLabelsDto):
    if type(text_id) is not int:
        raise HTTPException(status_code=400, detail="invalid BEN id")
    global_new_text_handler.update_labels(text_id=text_id, labels=dto.labels)
    return {"updated": True}


@router.patch("/{text_id}/part")
async def update_part(text_id: int, dto: UpdatePartDto):
    if type(text_id) is not int:
        raise HTTPException(status_code=400, detail="invalid BEN id")
    global_new_text_handler.update_part(text_id=text_id, part=dto.part)
    return {"updated": True}


@router.patch("/{text_id}/identifiers")
async def update_identifiers(text_id: int, dto: UpdateIdentifiersDto):
    if type(text_id) is not int:
        raise HTTPException(status_code=400, detail="invalid BEN id")
    global_new_text_handler.update_identifiers(
        text_id=text_id,
        museum_id=dto.museum_id,
        p_number=dto.p_number,
        publication_id=dto.publication_id
    )
    return {"updated": True}
