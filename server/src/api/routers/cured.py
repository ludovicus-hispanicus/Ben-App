# Auth removed for desktop app
# from auth.auth_bearer import JWTBearer
from typing import Optional

from api.dto.get_predictions import CureDGetTransliterationsDto

from fastapi import APIRouter, File, UploadFile, Form, BackgroundTasks, Request, HTTPException
from pydantic import BaseModel

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

@router.get("/museums")
async def get_museums():
    """
    Get museum abbreviations and full names from museums.csv.
    Returns a dictionary mapping abbreviation to full description.
    """
    import csv

    museums = {}
    csv_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "museums.csv")

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    # First column is abbreviation (may have spaces/slashes)
                    # Second column is description
                    abbrev = row[0].strip()
                    description = row[1].strip()

                    # Handle multiple abbreviations separated by " / "
                    # e.g., "A / A." -> store under "A" and "A."
                    parts = abbrev.split(" / ")
                    for part in parts:
                        clean_abbrev = part.strip().rstrip('.')
                        if clean_abbrev:
                            museums[clean_abbrev] = description
    except FileNotFoundError:
        logging.warning(f"museums.csv not found at {csv_path}")
    except Exception as e:
        logging.error(f"Error reading museums.csv: {e}")

    return museums


@router.get("/available-models")
async def get_available_models():
    """List all available OCR models (static + custom trained + VLM models)."""
    from services.kraken_training_service import kraken_training_service
    import json as _json

    models = []

    # Add static base models (Kraken)
    static_labels = {
        "latest": "Latest (Pennsylvania Sumerian Dictionary)",
        "dillard": "Dillard (Typewriter texts)",
        "base": "Base (SAA Corpus)",
    }
    for key, label in static_labels.items():
        model_file = CuredHandler.MODEL_FILES.get(key)
        if model_file and os.path.exists(f"./cured_models/{model_file}"):
            models.append({"value": key, "label": label, "is_custom": False})

    # Add DeepSeek-OCR-2 if available (VLM-based OCR)
    try:
        from services import deepseek_ocr_service
        if deepseek_ocr_service.is_available():
            models.append({
                "value": "deepseek",
                "label": "DeepSeek-OCR-2 (VLM, 3B params)",
                "is_custom": False,
                "is_vlm": True
            })
            logging.info("DeepSeek-OCR-2 added to available models")
    except ImportError:
        logging.debug("DeepSeek-OCR-2 not available")

    # Add custom trained models from registry
    registry_path = os.path.join(kraken_training_service.MODELS_DIR, "registry.json")
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r") as f:
                registry = _json.load(f)
            for entry in registry:
                name = entry.get("name", "")
                if name not in CuredHandler.MODEL_FILES:
                    model_path = f"./cured_models/{name}.mlmodel"
                    if os.path.exists(model_path):
                        accuracy = entry.get("accuracy", 0)
                        epochs = entry.get("epochs", 0)
                        label = f"{name} (Custom, {accuracy*100:.1f}% acc, {epochs} epochs)"
                        models.append({"value": name, "label": label, "is_custom": True})
        except Exception as e:
            logging.warning(f"Could not read model registry: {e}")

    return {"models": models}


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
    codec_size = stats.get("codec_size", 0)
    unique_characters = stats.get("unique_characters", [])
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
        "codecSize": codec_size,
        "uniqueCharacters": unique_characters,
        "requiredForNextTraining": required_for_training,
        "progress": progress,
        "isReady": lines_for_progress >= required_for_training,
        "lastTraining": last_training,
        "currentTraining": current_training
    }


@router.post("/training/start")
async def start_training(background_tasks: BackgroundTasks, epochs: int = 500, model_name: str = None, base_model: str = None):
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

    # Resolve base_model key (e.g. "dillard") to actual file path
    base_model_path = None
    if base_model:
        logging.info(f"[start_training] Received base_model key: {base_model}")
        model_file = CuredHandler.MODEL_FILES.get(base_model)
        logging.info(f"[start_training] MODEL_FILES lookup: {model_file}")
        if model_file:
            base_model_path = f"./cured_models/{model_file}"
            logging.info(f"[start_training] Resolved base_model_path: {base_model_path}")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown base model: {base_model}")

    # Start training in background
    # Use a sync wrapper with asyncio.run() since BackgroundTasks runs in a thread pool
    def run_training_sync():
        asyncio.run(kraken_training_service.start_training(
            texts_handler=global_new_text_handler,
            epochs=epochs,
            model_name=model_name,
            base_model=base_model_path
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


@router.get("/training/base-models")
async def get_base_models_metadata():
    """Get metadata for all available base models (for the training selector)."""
    from kraken.lib import vgsl
    results = {}
    for key, filename in CuredHandler.MODEL_FILES.items():
        model_path = f"./cured_models/{filename}"
        try:
            if not os.path.exists(model_path):
                continue
            stat = os.stat(model_path)
            nn = vgsl.TorchVGSLModel.load_model(model_path)
            meta = nn.user_metadata if hasattr(nn, 'user_metadata') else {}
            accuracy_list = meta.get("accuracy", [])
            best_accuracy = max((a[1] for a in accuracy_list), default=0) if accuracy_list else 0
            last_accuracy = accuracy_list[-1][1] if accuracy_list else 0
            hyper = meta.get("hyper_params", {})
            results[key] = {
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "best_accuracy": round(best_accuracy * 100, 1),
                "last_accuracy": round(last_accuracy * 100, 1),
                "completed_epochs": hyper.get("completed_epochs", 0),
                "alphabet_size": len(nn.codec.c2l) if hasattr(nn, 'codec') else 0,
            }
        except Exception as e:
            logging.warning(f"Could not load metadata for {key}: {e}")
    return results


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


# =============================================================================
# Translation Workflow Endpoints
# =============================================================================

@router.get("/translation/find")
async def find_translation_for_text(museum_name: str, museum_number: int):
    """
    Find a translation text matching the given museum identifier.
    Used by CuReD to enable translation toggle mode.

    Args:
        museum_name: Museum abbreviation (e.g., "BM", "K")
        museum_number: Museum accession number

    Returns:
        Translation text data if found, null otherwise
    """
    text = global_new_text_handler.find_translation_by_museum_number(
        museum_name=museum_name,
        museum_number=museum_number
    )

    if not text:
        return {"found": False, "text": None}

    # Get the latest transliteration data
    transliterations = global_new_text_handler.get_text_cured_transliterations(text_id=text.text_id)
    if not transliterations:
        return {"found": True, "text_id": text.text_id, "lines": []}

    latest_trans = transliterations[-1]
    latest_edit = latest_trans.edit_history[-1] if latest_trans.edit_history else None

    return {
        "found": True,
        "text_id": text.text_id,
        "transliteration_id": latest_trans.transliteration_id,
        "lines": latest_edit.lines if latest_edit else []
    }


@router.get("/transliteration/find")
async def find_transliteration_for_translation(museum_name: str, museum_number: int):
    """
    Find the source transliteration for a given museum identifier.
    Used when viewing a translation to navigate back to its source.

    Args:
        museum_name: Museum abbreviation (e.g., "BM", "K")
        museum_number: Museum accession number

    Returns:
        Transliteration text data if found, null otherwise
    """
    text = global_new_text_handler.find_transliteration_by_museum_number(
        museum_name=museum_name,
        museum_number=museum_number
    )

    if not text:
        return {"found": False, "text": None}

    # Get the latest transliteration data
    transliterations = global_new_text_handler.get_text_cured_transliterations(text_id=text.text_id)
    if not transliterations:
        return {"found": True, "text_id": text.text_id, "transliteration_id": None}

    latest_trans = transliterations[-1]

    return {
        "found": True,
        "text_id": text.text_id,
        "transliteration_id": latest_trans.transliteration_id
    }


@router.post("/createSubmission")
async def submit(request: Request, submit_dto: CuredSubmissionDto):
    user_id = request.state.user_id or "admin"  # Default to admin if not authenticated

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


# =============================================================================
# DeepSeek OCR Endpoints (VLM-based OCR with XML output support)
# =============================================================================

@router.get("/deepseek/output-modes")
async def get_deepseek_output_modes():
    """Get available output modes for DeepSeek OCR (plain text, TEI XML, etc.)"""
    try:
        from services import deepseek_ocr_service
        if not deepseek_ocr_service.is_available():
            raise HTTPException(status_code=503, detail="DeepSeek OCR not available (no GPU)")
        return {
            "modes": deepseek_ocr_service.get_available_output_modes(),
            "default": "plain"
        }
    except ImportError:
        raise HTTPException(status_code=503, detail="DeepSeek OCR service not installed")


@router.get("/deepseek/status")
async def get_deepseek_status():
    """Get DeepSeek OCR model status and memory usage"""
    try:
        from services import deepseek_ocr_service
        return {
            "available": deepseek_ocr_service.is_available(),
            "loaded": deepseek_ocr_service.is_loaded(),
            "info": deepseek_ocr_service.get_model_info()
        }
    except ImportError:
        return {"available": False, "loaded": False, "info": {}}


class DeepSeekOcrRequest(BaseModel):
    image: str  # Base64 encoded image
    output_mode: str = "plain"  # plain, tei_lex0, tei_epidoc
    custom_prompt: Optional[str] = None


@router.post("/deepseek/ocr")
async def deepseek_ocr(request: DeepSeekOcrRequest):
    """
    Run DeepSeek OCR on an image with selectable output format.

    Output modes:
    - plain: Plain text transcription
    - tei_lex0: TEI Lex-0 XML for dictionary entries
    - tei_epidoc: TEI EpiDoc XML for cuneiform texts
    """
    try:
        from services import deepseek_ocr_service

        if not deepseek_ocr_service.is_available():
            raise HTTPException(status_code=503, detail="DeepSeek OCR not available (no GPU)")

        result = deepseek_ocr_service.ocr_from_base64(
            image_base64=request.image,
            prompt=request.custom_prompt,
            output_mode=request.output_mode,
        )

        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("error", "OCR failed"))

        return result

    except ImportError:
        raise HTTPException(status_code=503, detail="DeepSeek OCR service not installed")


@router.post("/deepseek/unload")
async def unload_deepseek_model():
    """Unload DeepSeek model to free GPU memory"""
    try:
        from services import deepseek_ocr_service
        deepseek_ocr_service.unload_model()
        return {"message": "Model unloaded", "info": deepseek_ocr_service.get_model_info()}
    except ImportError:
        raise HTTPException(status_code=503, detail="DeepSeek OCR service not installed")


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
