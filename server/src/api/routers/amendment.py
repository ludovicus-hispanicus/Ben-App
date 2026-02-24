import logging
from typing import Optional, List, Union

from fastapi import APIRouter, Depends, File, UploadFile, Form, Request, HTTPException
from fastapi.responses import FileResponse

from api.dto.detectron_settings import DetectronSettings
from api.dto.get_predictions import GetSpecificPredictionsDto, GetPredictionsDto, PredictionsDto
from api.dto.letter import SignsData
from api.dto.stage_one import StageOneDto
from api.dto.submit import SubmitDto
from api.dto.text import NewTextPreviewDto
# Auth removed for desktop app
# from auth.auth_bearer import JWTBearer
from clients.translator_client import TranslatorClient
from common.global_handlers import global_ai_handler, global_texts_handler
from entities.dimensions import Dimensions
from entities.text import Uploader
from handlers.curei_handler import CureIHandler
from utils.storage_utils import StorageUtils

router = APIRouter(
    prefix="/api/v1/amendment",
    tags=["items"],
    responses={404: {"description": "Not found"}},
)


@router.post("/stageOne")
async def stage_one(request: Request,
                    requested_text_id: Optional[str] = Form(None),
                    old_text_id: Optional[str] = Form(None),
                    use_detectron: bool = Form(True),
                    detectron_sensitivity: float = Form(0.5)) -> StageOneDto:
    if not request.state.user_id:
        logging.debug(f">> amendment request from ip {request.client.host}:{request.client.port}"
                      f" that is not logged in <<")

    return await CureIHandler.get_stage_one(requested_text_id=requested_text_id,
                                            old_text_id=old_text_id,
                                            detectron_settings=
                                            DetectronSettings(use_detectron=use_detectron,
                                                              detectron_sensitivity=detectron_sensitivity))


@router.post("/generateBoxes")
async def get_specific_predictions(text_id: str = Form(None),
                                   use_detectron: bool = Form(True),
                                   detectron_sensitivity: float = Form(0.5)) -> List[List[Union[Dimensions, None]]]:
    logging.info(f"generate boxes predictions for text {text_id}")

    text = global_texts_handler.get_by_text_id(text_id)
    detectron_settings = DetectronSettings(use_detectron=use_detectron, detectron_sensitivity=detectron_sensitivity)
    return global_ai_handler.get_text_bounding_boxes(text_id=text.text_id,
                                                     detectron_settings=detectron_settings,
                                                     text_origin=Uploader(text.origin))


@router.get("/signsData")
async def get_sign_data() -> SignsData:
    return SignsData(label_to_unicode=global_ai_handler.label_to_unicode_new,
                     unicode_to_labels=global_ai_handler.unicode_to_labels)


@router.get("/lastCureiTexts")
async def get_sign_data() -> SignsData:
    return global_texts_handler.get_last_texts()


@router.get("/amendmentStats")
async def get_amendment_stats():
    return global_texts_handler.get_amendment_stats()


@router.get("/image/{name}")
async def images(name: int):
    if type(name) is not int or name > 100000000000000:
        raise HTTPException(status_code=500, detail="Invalid image name.")

    return FileResponse(StorageUtils().get_text_image_path(text_id=name))


@router.post("/predictions")
async def get_predictions(dto: GetPredictionsDto):
    predictions = await CureIHandler.get_predictions_of_text(dimensions=dto.dimensions,
                                                             text_id=dto.text_id)
    text = [" ".join(letter.symbol for letter in line) for line in predictions]

    try:
        generated_signs = TranslatorClient.translate(text)
    except Exception as e:
        logging.error(f"Couldn't use translator, error: {e}")
        generated_signs = []
        # for _ in range(len(predictions)):
        #     generated_signs.append("{GIŠ}-ma-NA ia₂ DU₆.KU₃")

    return PredictionsDto(predictions=predictions, sign_translation=generated_signs)


@router.post("/specificPredictions")
async def get_specific_predictions(dto: GetSpecificPredictionsDto):
    logging.info(f"get specific predictions for text {dto.text_id}")
    text = global_texts_handler.get_text(text_id=dto.text_id)
    return global_ai_handler.get_text_specific_predictions(text=text, bounding_boxes=dto.dimensions)


@router.post("/submit/")
async def submit(request: Request, submit_dto: SubmitDto):
    logging.info(submit_dto)
    logging.info(f"submit text id, {submit_dto.text_id}")
    logging.debug(f"submit text id, {submit_dto}")

    global_texts_handler.process_text_result(submit_dto=submit_dto, user_id=request.state.user_id or "admin")
    global_ai_handler.process_submit_result(submit_dto=submit_dto)
    return global_texts_handler.get_amendment_stats()


@router.post("/set-in-progress/{text_id}")
async def set_in_progress(request: Request, text_id: int):
    logging.info(f"set text {text_id} in progress")
    global_texts_handler.set_text_in_progress(text_id=text_id)

@router.post("/stageOneFile")
async def stage_one_file(request: Request, file: UploadFile = File(...), old_text_id=Form(...),
                         use_detectron: bool = Form(True),
                         detectron_sensitivity: float = Form(0.5)) -> StageOneDto:
    user_id = request.state.user_id or "admin"  # Default to admin if not authenticated

    StorageUtils.validate_image_file_type(file=file)

    return await CureIHandler.get_stage_one(old_text_id=old_text_id, file=file, user_id=user_id,
                                            detectron_settings=
                                            DetectronSettings(use_detectron=use_detectron,
                                                              detectron_sensitivity=detectron_sensitivity))

@router.get("/textBySymbol/{symbol}")
async def get_text_ids_by_symbol(symbol: str) -> List[NewTextPreviewDto]:
    logging.info(f"search text by symbol {symbol}")

    return global_texts_handler.get_by_symbol(symbol=symbol)


@router.get("/randomTexts/")
async def get_random_texts() -> List[NewTextPreviewDto]:
    logging.info(f"get random texts")

    return global_texts_handler.get_random_texts()