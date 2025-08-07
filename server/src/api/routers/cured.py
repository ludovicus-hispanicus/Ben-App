from auth.auth_bearer import JWTBearer
from api.dto.get_predictions import CureDGetTransliterationsDto

from fastapi import APIRouter, File, UploadFile, Form, BackgroundTasks, Request, Depends, HTTPException

from api.dto.submissions import TransliterationSubmitDto, CuredSubmissionDto, CuredTransliterationData
from entities.new_text import TransliterationSource
from common.global_handlers import global_new_text_handler
from handlers.cured_handler import CuredHandler
from utils.pdf_utils import PdfUtils
from utils.storage_utils import StorageUtils
from fastapi.responses import FileResponse
import logging

router = APIRouter(
    prefix="/api/v1/cured",
    tags=["items"],
    responses={404: {"description": "Not found"}}
)


@router.post("/createSubmission", dependencies=[Depends(JWTBearer())])
async def submit(request: Request, submit_dto: CuredSubmissionDto):
    user_id = request.state.user_id

    submit_dto = TransliterationSubmitDto(
        text_id=submit_dto.text_id,
        transliteration_id=submit_dto.transliteration_id,
        lines=submit_dto.lines,
        boxes=submit_dto.boxes,
        source=TransliterationSource.CURED,
        image_name=submit_dto.image_name or "",
        is_fixed=submit_dto.is_fixed,
    )

    transliteration_id = global_new_text_handler.save_new_transliteration(dto=submit_dto, uploader_id=user_id)
    return transliteration_id


@router.post("/saveImage/", dependencies=[Depends(JWTBearer())])
async def save_text_image(request: Request, file: UploadFile = File(...), text_id=Form(...)):
    StorageUtils.validate_image_file_type(file=file)

    new_name = StorageUtils.generate_cured_train_image_name(original_file_name=file.filename, text_id=text_id)
    path = StorageUtils.build_cured_train_image_path(image_name=new_name)
    preview_path = StorageUtils.build_preview_image_path(image_name=new_name)
    await StorageUtils.save_uploaded_image(file=file, path=path)
    StorageUtils.make_a_preview(image_path=path, preview_path=preview_path)

    return new_name


@router.post("/convertPdf/")
async def convert_pdf(background_tasks: BackgroundTasks, raw_pdf: UploadFile = File(...),
                      page: int = Form(...)):
    logging.info(f"convert pdf, {page} {raw_pdf.content_type}")
    if raw_pdf.content_type != "application/pdf":
        return TypeError("Invalid file!")

    pdf_bytes = await raw_pdf.read()
    page_png_bytes = PdfUtils.extract_page_as_png(pdf_bytes=pdf_bytes, page=page)
    temp_file, temp_file_path = StorageUtils.create_temp_file()
    try:
        StorageUtils.write_to_file(file=temp_file, content=page_png_bytes)
    finally:
        background_tasks.add_task(StorageUtils.delete_file, temp_file_path)

    return FileResponse(temp_file_path)


@router.get("/{ben_id}/transliterations")
async def get_text_transliterations(ben_id: int):
    if type(ben_id) is not int:
        raise HTTPException(status_code=500, detail="invalid BEN id")

    return global_new_text_handler.get_text_cured_transliterations_preview(ben_id)


@router.post("/getTransliterations")
async def get_transliterations(background_tasks: BackgroundTasks, dto: CureDGetTransliterationsDto):
    return CuredHandler.get_transliterations(dto=dto, background_tasks=background_tasks)


@router.get("/transliteration/{text_id}/{transliteration_id}")
async def fetch_transliteration_by_id(text_id: int, transliteration_id: int):
    if type(text_id) is not int or type(transliteration_id) is not int:
        raise HTTPException(status_code=500, detail="invalid BEN / transliteration id")

    transliterations = global_new_text_handler.get_text_cured_transliterations(text_id=text_id)
    trans = next(trans for trans in transliterations if trans.transliteration_id == transliteration_id)
    if not trans:
        raise HTTPException(status_code=500, detail="Transliteration doesn't exist")

    return CuredTransliterationData.from_transliteration_entity(entity=trans)


@router.get("/transliterationImage/{text_id}/{transliteration_id}")
async def get_image(text_id: int, transliteration_id: int):
    if type(text_id) is not int or type(transliteration_id) is not int:
        raise HTTPException(status_code=500, detail="invalid BEN / transliteration id")

    transliterations = global_new_text_handler.get_text_cured_transliterations(text_id=text_id)
    trans = next(trans for trans in transliterations if trans.transliteration_id == transliteration_id)
    if not trans:
        raise HTTPException(status_code=500, detail="Transliteration doesn't exist")

    image_name = trans.image_name

    return FileResponse(StorageUtils.build_cured_train_image_path(image_name=image_name))
