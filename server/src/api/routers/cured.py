# Auth removed for desktop app
# from auth.auth_bearer import JWTBearer
from api.dto.get_predictions import CureDGetTransliterationsDto

from fastapi import APIRouter, File, UploadFile, Form, BackgroundTasks, Request, HTTPException

from api.dto.submissions import TransliterationSubmitDto, CuredSubmissionDto, CuredTransliterationData
from entities.new_text import TransliterationSource
from common.global_handlers import global_new_text_handler
from handlers.cured_handler import CuredHandler
from utils.pdf_utils import PdfUtils
from utils.storage_utils import StorageUtils
from fastapi.responses import FileResponse
import logging
import os

router = APIRouter(
    prefix="/api/v1/cured",
    tags=["items"],
    responses={404: {"description": "Not found"}}
)


# Static routes must come BEFORE parameterized routes
@router.get("/training/status")
async def get_training_status():
    """Get the current training data status for Kraken OCR model."""
    from services.kraken_training_service import kraken_training_service, TrainingStatus

    # Get stats with previous/new breakdown
    stats = kraken_training_service.get_training_stats(global_new_text_handler)
    logging.info(f"Training stats: {stats}")

    previous_lines = stats.get("previous_lines", 0)
    new_lines = stats.get("new_lines", 0)
    total_lines = stats.get("total_lines", 0)
    curated_texts = stats.get("curated_texts", 0)
    last_training = stats.get("last_training")
    required_for_training = 1000  # Minimum lines required for training

    # Progress: use total_lines before first training, new_lines after
    lines_for_progress = new_lines if last_training else total_lines
    progress = min(100, int((lines_for_progress / required_for_training) * 100)) if required_for_training > 0 else 0

    # Include current training status if training is in progress
    current_training = None
    if kraken_training_service.progress.status != TrainingStatus.IDLE:
        current_training = kraken_training_service.progress.to_dict()

    return {
        "curatedTexts": curated_texts,
        "previousLines": previous_lines,
        "newLines": new_lines,
        "totalLines": total_lines,
        "requiredForNextTraining": required_for_training,
        "progress": progress,
        "isReady": lines_for_progress >= required_for_training,
        "lastTraining": last_training,
        "currentTraining": current_training
    }


@router.post("/training/start")
async def start_training(background_tasks: BackgroundTasks, epochs: int = 50, model_name: str = None):
    """Start Kraken OCR model training."""
    from services.kraken_training_service import kraken_training_service, TrainingStatus
    import asyncio

    # Check if already training
    if kraken_training_service.progress.status == TrainingStatus.TRAINING:
        raise HTTPException(status_code=409, detail="Training already in progress")

    # Validate training data
    curated_stats = global_new_text_handler.get_curated_training_stats()
    total_lines = curated_stats.get("total_lines", 0)

    if total_lines < 1000:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough training data. Need at least 1000 lines, got {total_lines}"
        )

    # Start training in background
    # Use a sync wrapper with asyncio.run() since BackgroundTasks runs in a thread pool
    def run_training_sync():
        asyncio.run(kraken_training_service.start_training(
            texts_handler=global_new_text_handler,
            epochs=epochs,
            model_name=model_name
        ))

    background_tasks.add_task(run_training_sync)

    return {
        "message": "Training started",
        "epochs": epochs,
        "model_name": model_name
    }


@router.get("/training/progress")
async def get_training_progress():
    """Get current training progress."""
    from services.kraken_training_service import kraken_training_service
    return kraken_training_service.progress.to_dict()


@router.post("/training/cancel")
async def cancel_training():
    """Cancel ongoing training."""
    from services.kraken_training_service import kraken_training_service, TrainingStatus

    if kraken_training_service.progress.status != TrainingStatus.TRAINING:
        raise HTTPException(status_code=400, detail="No training in progress")

    kraken_training_service.cancel_training()
    return {"message": "Training cancelled"}


@router.get("/training/models")
async def list_models():
    """List available trained models."""
    from services.kraken_training_service import kraken_training_service
    models = kraken_training_service.get_models()
    return {"models": models}


@router.get("/training/active-model")
async def get_active_model():
    """Get information about the currently active OCR model."""
    from services.kraken_training_service import kraken_training_service
    return kraken_training_service.get_active_model_info()


@router.post("/training/models/{model_name}/activate")
async def activate_model(model_name: str):
    """Set a model as the active OCR model."""
    from services.kraken_training_service import kraken_training_service

    success = kraken_training_service.activate_model(model_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_name}")

    return {"message": f"Model {model_name} activated"}


@router.post("/createSubmission")
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


@router.post("/saveImage/")
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
    if not image_name:
        raise HTTPException(status_code=404, detail="No image associated with this transliteration")

    image_path = StorageUtils.build_cured_train_image_path(image_name=image_name)
    if not os.path.isfile(image_path):
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(image_path)


@router.delete("/{text_id}")
async def delete_text(text_id: int):
    if type(text_id) is not int:
        raise HTTPException(status_code=400, detail="invalid BEN id")

    global_new_text_handler.delete_text(text_id=text_id)
    return {"deleted": "text"}


@router.delete("/{text_id}/{transliteration_id}")
async def delete_transliteration(text_id: int, transliteration_id: int):
    if type(text_id) is not int or type(transliteration_id) is not int:
        raise HTTPException(status_code=400, detail="invalid BEN / transliteration id")

    remaining = global_new_text_handler.delete_transliteration(
        text_id=text_id, transliteration_id=transliteration_id
    )

    if remaining == -1:
        raise HTTPException(status_code=404, detail="Text not found")

    if remaining == 0:
        global_new_text_handler.delete_text(text_id=text_id)
        return {"deleted": "text"}

    return {"deleted": "transliteration"}


# ==========================================
# Akkadian Post-Processor Endpoints
# ==========================================

@router.get("/postprocessor/stats")
async def get_postprocessor_stats():
    """Get statistics about the Akkadian post-processor rules."""
    try:
        from services.akkadian_post_processor import akkadian_post_processor
        return akkadian_post_processor.get_stats()
    except ImportError:
        raise HTTPException(status_code=503, detail="Post-processor not available")


@router.get("/postprocessor/rules")
async def get_postprocessor_rules():
    """Get all current post-processor rules."""
    try:
        from services.akkadian_post_processor import akkadian_post_processor
        return akkadian_post_processor.rules
    except ImportError:
        raise HTTPException(status_code=503, detail="Post-processor not available")


@router.post("/postprocessor/reload")
async def reload_postprocessor_rules():
    """Reload rules from file."""
    try:
        from services.akkadian_post_processor import akkadian_post_processor
        akkadian_post_processor.reload_rules()
        return {"message": "Rules reloaded", "stats": akkadian_post_processor.get_stats()}
    except ImportError:
        raise HTTPException(status_code=503, detail="Post-processor not available")


@router.post("/postprocessor/test")
async def test_postprocessor(text: str):
    """Test the post-processor with a sample text."""
    try:
        from services.akkadian_post_processor import akkadian_post_processor
        result = akkadian_post_processor.process_text(text)
        return result.to_dict()
    except ImportError:
        raise HTTPException(status_code=503, detail="Post-processor not available")


from pydantic import BaseModel
from typing import List


class ApplyPostProcessingDto(BaseModel):
    lines: List[str]


@router.post("/postprocessor/apply")
async def apply_postprocessing(dto: ApplyPostProcessingDto):
    """Apply Akkadian post-processing rules to a list of lines."""
    try:
        from services.akkadian_post_processor import akkadian_post_processor
        results = akkadian_post_processor.process_lines(dto.lines)
        return {
            "lines": [r.corrected_text for r in results],
            "corrections": [r.to_dict() for r in results if r.corrections]
        }
    except ImportError:
        raise HTTPException(status_code=503, detail="Post-processor not available")


class AddRuleDto(BaseModel):
    rule_type: str  # 'invalid_sequences' or 'custom_replacements'
    pattern: str
    replacement: str
    description: str = ""


@router.post("/postprocessor/rules")
async def add_postprocessor_rule(dto: AddRuleDto):
    """Add a new rule to the post-processor."""
    try:
        from services.akkadian_post_processor import akkadian_post_processor

        rule = {
            "pattern": dto.pattern,
            "replacement": dto.replacement,
            "description": dto.description
        }

        success = akkadian_post_processor.add_rule(dto.rule_type, rule)
        if success:
            # Save to file so it persists
            akkadian_post_processor.save_rules()
            return {"message": "Rule added", "rule": rule}
        else:
            raise HTTPException(status_code=400, detail="Failed to add rule")
    except ImportError:
        raise HTTPException(status_code=503, detail="Post-processor not available")
