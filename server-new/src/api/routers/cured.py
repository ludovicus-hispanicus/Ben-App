# Auth removed for desktop app
# from auth.auth_bearer import JWTBearer
from api.dto.get_predictions import CureDGetTransliterationsDto
from pydantic import BaseModel

from typing import List, Optional
from fastapi import APIRouter, File, UploadFile, Form, BackgroundTasks, Request, HTTPException, Query

from api.dto.submissions import TransliterationSubmitDto, CuredSubmissionDto, CuredTransliterationData, BatchCurateDto
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
                    abbrev = row[0].strip()
                    description = row[1].strip()

                    # Handle multiple abbreviations separated by " / "
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


@router.get("/nemotron/status")
async def get_nemotron_status():
    """Get Nemotron OCR engine status and configuration."""
    return CuredHandler.get_nemotron_status()


@router.get("/gpu/status")
async def get_gpu_status():
    """Get GPU availability and loaded models status."""
    from clients.ocr_factory import _local_nemotron_client

    result = {
        "cuda_available": False,
        "gpu_name": None,
        "gpu_memory_gb": None,
        "models": {
            "nemotron_local": {
                "available": False,
                "loaded": False,
                "requires_preload": True,
                "vram_required_gb": 1.7,
            }
        }
    }

    try:
        import torch
        result["cuda_available"] = torch.cuda.is_available()
        if result["cuda_available"]:
            result["gpu_name"] = torch.cuda.get_device_name(0)
            result["gpu_memory_gb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 1)
            # Nemotron is available if CUDA is available
            result["models"]["nemotron_local"]["available"] = True
    except ImportError:
        pass

    # Check if Nemotron is already loaded
    result["models"]["nemotron_local"]["loaded"] = _local_nemotron_client is not None

    return result


@router.post("/gpu/preload/{model_name}")
async def preload_gpu_model(model_name: str):
    """Preload a GPU model to avoid delay on first use."""
    if model_name == "nemotron_local":
        try:
            from clients.ocr_factory import preload_nemotron_local
            preload_nemotron_local()
            return {"message": "Nemotron model loaded successfully", "loaded": True}
        except Exception as e:
            logging.error(f"Failed to preload Nemotron: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")


@router.post("/gpu/unload/{model_name}")
async def unload_gpu_model(model_name: str):
    """Unload a GPU model to free VRAM for other models."""
    if model_name == "nemotron_local":
        try:
            import clients.ocr_factory as ocr_factory
            if ocr_factory._local_nemotron_client is not None:
                # Clear the cached model
                del ocr_factory._local_nemotron_client._model
                del ocr_factory._local_nemotron_client._processor
                ocr_factory._local_nemotron_client = None

                # Force GPU memory cleanup
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()

                logging.info("Nemotron model unloaded, GPU memory freed")
                return {"message": "Nemotron model unloaded", "loaded": False}
            else:
                return {"message": "Nemotron model was not loaded", "loaded": False}
        except Exception as e:
            logging.error(f"Failed to unload Nemotron: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")


@router.get("/ollama/models")
async def get_ollama_models():
    """Get list of available Ollama vision models."""
    from services.ollama_ocr_service import OllamaOcrService
    service = OllamaOcrService()
    if not service.is_available():
        return []
    models = service.list_models()
    # Filter for vision-capable models
    vision_models = []
    for m in models:
        name = m.get("name", "")
        if any(v in name.lower() for v in ["llava", "qwen", "minicpm", "bakllava", "moondream", "deepseek", "llama4", "mistral"]):
            vision_models.append(name)
    return vision_models


@router.get("/ollama/recommended-models")
async def get_recommended_models():
    """Get list of recommended VLM models for OCR with installation status."""
    from services.ollama_ocr_service import OllamaOcrService
    service = OllamaOcrService()

    # Recommended models for OCR - ordered by recommendation (smallest first for 8GB GPUs)
    recommended = [
        {
            "id": "qwen3-vl:4b",
            "name": "Qwen3 VL 4B",
            "description": "Best for 8GB GPU - fast, light",
            "size_gb": 2.5,
            "vram_gb": 4,
            "installed": False
        },
        {
            "id": "deepseek-ocr",
            "name": "DeepSeek OCR",
            "description": "Specialized OCR model - 3B params",
            "size_gb": 2.0,
            "vram_gb": 3,
            "installed": False
        },
        {
            "id": "qwen3-vl:8b",
            "name": "Qwen3 VL 8B",
            "description": "Best OCR quality for 12GB+ GPU",
            "size_gb": 6.0,
            "vram_gb": 8,
            "installed": False
        },
        {
            "id": "llama4:scout",
            "name": "Llama 4 Scout",
            "description": "Meta's latest VLM - most capable",
            "size_gb": 12.0,
            "vram_gb": 14,
            "installed": False
        },
        {
            "id": "mistral-small3.1",
            "name": "Mistral Small 3.1",
            "description": "24B params with vision - needs 16GB+",
            "size_gb": 15.0,
            "vram_gb": 18,
            "installed": False
        },
        {
            "id": "qwen3-vl:32b",
            "name": "Qwen3 VL 32B",
            "description": "Highest quality - needs 24GB+ VRAM",
            "size_gb": 21.0,
            "vram_gb": 24,
            "installed": False
        },
    ]

    if not service.is_available():
        return {"ollama_available": False, "models": recommended}

    # Check which models are installed
    installed_models = service.list_models()
    # Get full model names (e.g., "qwen3-vl:8b", "deepseek-ocr:latest")
    installed_names = [m.get("name", "") for m in installed_models]

    for model in recommended:
        model_id = model["id"]  # e.g., "qwen3-vl:4b"
        model_base = model_id.split(":")[0]  # e.g., "qwen3-vl"

        # Check for exact match or same base with matching tag
        # Don't match cloud models (235b-cloud) with local models (4b, 8b, 32b)
        model["installed"] = any(
            name == model_id or  # Exact match
            name.startswith(model_id) or  # e.g., "qwen3-vl:4b" matches "qwen3-vl:4b-q4"
            (name.split(":")[0] == model_base and  # Same base name
             "cloud" not in name.lower() and  # Not a cloud model
             (len(name.split(":")) == 1 or  # No tag (e.g., "deepseek-ocr")
              name == f"{model_base}:latest"))  # Or :latest tag
            for name in installed_names
        )

    return {"ollama_available": True, "models": recommended}


@router.post("/ollama/pull/{model_name:path}")
async def pull_ollama_model(model_name: str, background_tasks: BackgroundTasks):
    """Start pulling/downloading an Ollama model."""
    from services.ollama_ocr_service import OllamaOcrService
    import httpx

    service = OllamaOcrService()
    if not service.is_available():
        raise HTTPException(status_code=503, detail="Ollama server is not running")

    # Check if already installed
    if service.is_model_available(model_name):
        return {"status": "already_installed", "model": model_name}

    # Start the pull - this returns immediately, client should poll status
    try:
        # Use streaming to track progress
        async def pull_with_progress():
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{service.base_url}/api/pull",
                    json={"name": model_name}
                ) as response:
                    async for line in response.aiter_lines():
                        pass  # Just drain the response

        background_tasks.add_task(pull_with_progress)
        return {"status": "started", "model": model_name}
    except Exception as e:
        logging.error(f"Failed to start model pull: {e}")
        raise HTTPException(status_code=500, detail=str(e))


from fastapi.responses import StreamingResponse
import json

@router.get("/ollama/pull/{model_name:path}/stream")
async def pull_ollama_model_stream(model_name: str):
    """Pull/download an Ollama model with streaming progress updates."""
    from services.ollama_ocr_service import OllamaOcrService
    import httpx

    service = OllamaOcrService()
    if not service.is_available():
        raise HTTPException(status_code=503, detail="Ollama server is not running")

    logging.info(f"Starting model pull: {model_name}")

    async def generate_progress():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{service.base_url}/api/pull",
                    json={"name": model_name, "stream": True}
                ) as response:
                    if response.status_code != 200:
                        error_msg = f"Ollama returned status {response.status_code}"
                        logging.error(error_msg)
                        yield f"data: {json.dumps({'status': 'error', 'error': error_msg})}\n\n"
                        return

                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                logging.debug(f"Ollama pull response: {data}")

                                # Check for error from Ollama
                                if "error" in data:
                                    error_msg = data["error"]
                                    logging.error(f"Ollama pull error: {error_msg}")
                                    yield f"data: {json.dumps({'status': 'error', 'error': error_msg})}\n\n"
                                    return

                                # Extract progress info
                                status = data.get("status", "")
                                total = data.get("total", 0)
                                completed = data.get("completed", 0)

                                # Calculate percent - handle different Ollama status messages
                                if total > 0:
                                    percent = int((completed / total) * 100)
                                elif "success" in status.lower():
                                    percent = 100
                                else:
                                    percent = 0

                                progress_data = {
                                    "status": status,
                                    "total": total,
                                    "completed": completed,
                                    "percent": percent
                                }
                                yield f"data: {json.dumps(progress_data)}\n\n"

                                # Check if Ollama signals completion
                                if status == "success" or "success" in status.lower():
                                    logging.info(f"Model pull completed: {model_name}")
                                    return

                            except json.JSONDecodeError as e:
                                logging.warning(f"Failed to parse Ollama response: {line}, error: {e}")

                    # Send completion if we finished the stream without explicit success
                    logging.info(f"Model pull stream ended: {model_name}")
                    yield f"data: {json.dumps({'status': 'success', 'percent': 100})}\n\n"
        except Exception as e:
            logging.error(f"Model pull exception: {e}")
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate_progress(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.get("/ollama/prompts")
async def get_ollama_prompts():
    """Get available OCR prompts."""
    from common.ocr_prompts import PROMPTS, BUILTIN_PROMPT_KEYS
    return {
        "prompts": [
            {"key": key, "value": value, "builtin": key in BUILTIN_PROMPT_KEYS}
            for key, value in PROMPTS.items()
        ]
    }


@router.post("/ollama/prompts")
async def create_ollama_prompt(body: dict):
    """Create a new custom OCR prompt."""
    from common.ocr_prompts import PROMPTS

    key = body.get("key", "").strip().lower().replace(" ", "_")
    value = body.get("value", "").strip()

    if not key:
        raise HTTPException(status_code=400, detail="Prompt key is required")
    if not value:
        raise HTTPException(status_code=400, detail="Prompt value is required")
    if key in PROMPTS:
        raise HTTPException(status_code=409, detail=f"Prompt '{key}' already exists")

    PROMPTS[key] = value
    return {"message": f"Prompt '{key}' created", "key": key, "value": value}


@router.put("/ollama/prompts/{prompt_key}")
async def update_ollama_prompt(prompt_key: str, body: dict):
    """Update an OCR prompt."""
    from common.ocr_prompts import PROMPTS
    if prompt_key not in PROMPTS:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found")

    new_value = body.get("value")
    if not new_value:
        raise HTTPException(status_code=400, detail="Prompt value is required")

    PROMPTS[prompt_key] = new_value
    return {"message": f"Prompt '{prompt_key}' updated", "key": prompt_key, "value": new_value}


@router.delete("/ollama/prompts/{prompt_key}")
async def delete_ollama_prompt(prompt_key: str):
    """Delete a custom OCR prompt (built-in prompts cannot be deleted)."""
    from common.ocr_prompts import PROMPTS, BUILTIN_PROMPT_KEYS

    if prompt_key not in PROMPTS:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found")
    if prompt_key in BUILTIN_PROMPT_KEYS:
        raise HTTPException(status_code=403, detail=f"Cannot delete built-in prompt '{prompt_key}'")

    del PROMPTS[prompt_key]
    return {"message": f"Prompt '{prompt_key}' deleted", "key": prompt_key}


@router.get("/ollama/default-prompt")
async def get_default_prompt():
    """Get the default OCR prompt key."""
    from common.ocr_prompts import get_default_prompt as _get_default
    return {"default_prompt": _get_default()}


@router.put("/ollama/default-prompt")
async def set_default_prompt(body: dict):
    """Set the default OCR prompt key."""
    from common.ocr_prompts import PROMPTS, set_default_prompt

    prompt_key = body.get("prompt_key")
    if not prompt_key:
        raise HTTPException(status_code=400, detail="prompt_key is required")

    if prompt_key not in PROMPTS:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found")

    set_default_prompt(prompt_key)
    return {"message": f"Default prompt set to '{prompt_key}'", "default_prompt": prompt_key}


@router.patch("/batch-curate")
async def batch_curate(request: Request, dto: BatchCurateDto):
    """Set or unset curation flags on multiple texts at once."""
    user_id = getattr(request.state, 'user_id', 'admin')
    result = global_new_text_handler.batch_curate(
        text_ids=dto.text_ids,
        curate=dto.curate,
        target=dto.target,
        user_id=user_id
    )
    return result


@router.get("/training/curated-stats")
async def get_curated_stats(project_id: int = None):
    """Get curated data stats broken down by target (kraken vs vlm) plus totals.
    Optionally filtered by project_id."""
    all_stats = global_new_text_handler.get_curated_training_stats(target=None, project_id=project_id)
    kraken_stats = global_new_text_handler.get_curated_training_stats(target="kraken", project_id=project_id)
    vlm_stats = global_new_text_handler.get_curated_training_stats(target="vlm", project_id=project_id)

    return {
        "total": {
            "lines": all_stats.get("total_lines", 0),
            "texts": all_stats.get("curated_texts", 0),
        },
        "kraken": {
            "lines": kraken_stats.get("total_lines", 0),
            "texts": kraken_stats.get("curated_texts", 0),
        },
        "vlm": {
            "lines": vlm_stats.get("total_lines", 0),
            "texts": vlm_stats.get("curated_texts", 0),
        },
    }


@router.get("/training/status")
async def get_training_status():
    """Get the current training data status for Nemotron LoRA fine-tuning."""
    from services.nemotron_training_service import nemotron_training_service, TrainingStatus

    # Get stats with previous/new breakdown
    stats = nemotron_training_service.get_training_stats(global_new_text_handler)
    logging.info(f"Nemotron training stats: {stats}")

    previous_lines = stats.get("previous_lines", 0)
    new_lines = stats.get("new_lines", 0)
    total_lines = stats.get("total_lines", 0)
    curated_texts = stats.get("curated_texts", 0)
    last_training = stats.get("last_training")
    required_for_training = 50  # LoRA is more data-efficient

    # Progress: use total_lines before first training, new_lines after
    lines_for_progress = total_lines
    progress = min(100, int((lines_for_progress / required_for_training) * 100)) if required_for_training > 0 else 0

    # Include current training status if training is in progress
    current_training = None
    if nemotron_training_service.progress.status != TrainingStatus.IDLE:
        current_training = nemotron_training_service.progress.to_dict()

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
async def start_training(background_tasks: BackgroundTasks, epochs: int = 3, model_name: str = None, base_model: str = None):
    """Start Nemotron LoRA fine-tuning."""
    from services.nemotron_training_service import nemotron_training_service, TrainingStatus
    import asyncio

    # Check if already training
    if nemotron_training_service.progress.status == TrainingStatus.TRAINING:
        raise HTTPException(status_code=409, detail="Training already in progress")

    # Validate training data
    stats = nemotron_training_service.get_training_stats(global_new_text_handler)
    previous_lines = stats.get("previous_lines", 0)
    new_lines = stats.get("new_lines", 0)
    total_lines = stats.get("total_lines", 0)
    last_training = stats.get("last_training")

    # Use new_lines after first training, total_lines before
    lines_for_training = total_lines
    min_required = 50  # LoRA is more data-efficient

    if lines_for_training < min_required:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough training data. Need at least {min_required} lines, got {lines_for_training}"
        )

    # Generate model name if not provided
    if not model_name:
        from datetime import datetime
        model_name = f"nemotron_lora_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Run training in background
    def run_training_sync():
        asyncio.run(nemotron_training_service.start_training(
            texts_handler=global_new_text_handler,
            epochs=epochs,
            model_name=model_name
        ))

    background_tasks.add_task(run_training_sync)
    return {"message": "LoRA training started", "epochs": epochs, "model_name": model_name}


@router.get("/training/progress")
async def get_training_progress():
    """Get current Nemotron LoRA training progress."""
    from services.nemotron_training_service import nemotron_training_service
    return nemotron_training_service.progress.to_dict()


@router.post("/training/cancel")
async def cancel_training():
    """Cancel ongoing Nemotron LoRA training."""
    from services.nemotron_training_service import nemotron_training_service, TrainingStatus

    if nemotron_training_service.progress.status != TrainingStatus.TRAINING:
        raise HTTPException(status_code=400, detail="No training in progress")

    nemotron_training_service.cancel_training()
    return {"message": "Training cancelled"}


@router.get("/training/models")
async def list_models():
    """List available LoRA adapter models."""
    from services.nemotron_training_service import nemotron_training_service
    models = nemotron_training_service.get_models()
    return {"models": models}


@router.get("/training/active-model")
async def get_active_model():
    """Get information about the currently active LoRA adapter."""
    from services.nemotron_training_service import nemotron_training_service
    return nemotron_training_service.get_active_model_info()


@router.post("/training/models/{model_name}/activate")
async def activate_model(model_name: str):
    """Set a LoRA adapter as the active model."""
    from services.nemotron_training_service import nemotron_training_service

    success = nemotron_training_service.activate_model(model_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"LoRA adapter not found: {model_name}")

    return {"message": f"LoRA adapter {model_name} activated"}


@router.get("/training/base-models")
async def get_base_models():
    """Get list of available base models for training."""
    return {
        "models": [
            {
                "id": "nvidia/NVIDIA-Nemotron-Parse-v1.1",
                "name": "Nemotron-Parse v1.1",
                "description": "NVIDIA's document parsing VLM"
            }
        ]
    }


@router.get("/available-models")
async def get_available_models():
    """Get list of available OCR models (providers + trained adapters + Kraken models)."""
    from services.nemotron_training_service import nemotron_training_service
    from services.kraken_training_service import kraken_training_service

    # Base OCR provider models (these match OCRFactory providers)
    models = [
        {"value": "gemini", "label": "Gemini (Google Cloud)"},
        {"value": "openai", "label": "GPT-4 Vision (OpenAI)"},
        {"value": "anthropic", "label": "Claude (Anthropic)"},
        {"value": "nemotron", "label": "Nemotron-Parse (NVIDIA Cloud)"},
        {"value": "nemotron-local", "label": "Nemotron-Parse (Local GPU)"},
    ]

    # Add Kraken models (locally trained OCR models)
    try:
        kraken_models = kraken_training_service.get_models()
        for km in kraken_models:
            models.append({
                "value": f"kraken:{km['name']}",
                "label": f"{km['name']} (Kraken)"
            })
    except Exception as e:
        logging.warning(f"Could not load Kraken models: {e}")

    # Add any trained LoRA adapters (Nemotron fine-tuned)
    try:
        adapters = nemotron_training_service.get_adapters()
        for adapter in adapters:
            models.append({
                "value": adapter["name"],
                "label": f"{adapter['name']} (Nemotron LoRA)"
            })
    except Exception as e:
        logging.warning(f"Could not load Nemotron adapters: {e}")

    # Add Qwen LoRA adapters
    try:
        from services.qwen_training_service import qwen_training_service
        qwen_adapters = qwen_training_service.get_adapters()
        for adapter in qwen_adapters:
            mode = adapter.get("output_mode", "plain")
            base = adapter.get("base_model", "qwen3-vl")
            models.append({
                "value": f"qwen_lora:{adapter['name']}",
                "label": f"{adapter['name']} (Qwen QLoRA, {base}, {mode})"
            })
    except Exception as e:
        logging.warning(f"Could not load Qwen adapters: {e}")

    # Add CuRe sign classifier models
    try:
        from services.cure_training_service import cure_training_service
        cure_models = cure_training_service.get_models()
        for cm in cure_models:
            models.append({
                "value": f"cure:{cm['name']}",
                "label": f"{cm['name']} (CuRe Sign Classifier)"
            })
    except Exception as e:
        logging.warning(f"Could not load CuRe models: {e}")

    # Add TrOCR fine-tuned models
    try:
        from services.trocr_training_service import trocr_training_service
        trocr_models = trocr_training_service.get_models()
        for tm in trocr_models:
            base = tm.get("base_model", "trocr")
            models.append({
                "value": f"trocr:{tm['name']}",
                "label": f"{tm['name']} (TrOCR, {base})"
            })
    except Exception as e:
        logging.warning(f"Could not load TrOCR models: {e}")

    return {"models": models}


# ==========================================
# Kraken OCR Training Endpoints
# ==========================================

@router.get("/training/kraken/status")
async def get_kraken_training_status(project_id: int = None, project_ids: Optional[List[int]] = Query(None)):
    """Get the current training data status for Kraken OCR fine-tuning."""
    from services.kraken_training_service import kraken_training_service, TrainingStatus

    # Normalise: single project_id → list for consistency
    pids = project_ids or ([project_id] if project_id is not None else None)

    # Get stats with previous/new breakdown
    stats = kraken_training_service.get_training_stats(global_new_text_handler, project_ids=pids)
    logging.info(f"Kraken training stats: {stats}")

    previous_lines = stats.get("previous_lines", 0)
    new_lines = stats.get("new_lines", 0)
    total_lines = stats.get("total_lines", 0)
    curated_texts = stats.get("curated_texts", 0)
    last_training = stats.get("last_training")
    required_for_training = kraken_training_service.MIN_LINES_FINETUNE

    # Progress: use total_lines before first training, new_lines after
    lines_for_progress = total_lines
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


@router.post("/training/kraken/start")
async def start_kraken_training(epochs: int = 500, model_name: str = None, base_model: str = None, batch_size: int = 1, device: str = "auto", patience: int = 10, project_id: int = None, project_ids: Optional[List[int]] = Query(None)):
    """Start Kraken OCR training, optionally scoped to one or more projects."""
    from services.kraken_training_service import kraken_training_service, TrainingStatus
    import asyncio

    # Normalise: single project_id → list for consistency
    pids = project_ids or ([project_id] if project_id is not None else None)

    # Check if already training
    if kraken_training_service.progress.status == TrainingStatus.TRAINING:
        raise HTTPException(status_code=409, detail="Training already in progress")

    # Check GPU availability (Kraken can use GPU when device != cpu)
    if device != "cpu":
        from services.gpu_lock import acquire as gpu_acquire
        ok, owner = gpu_acquire("kraken_training")
        if not ok:
            raise HTTPException(status_code=409, detail=f"GPU is busy ({owner}). Wait for it to finish or cancel it first.")

    # Validate training data
    stats = kraken_training_service.get_training_stats(global_new_text_handler, project_ids=pids)
    previous_lines = stats.get("previous_lines", 0)
    new_lines = stats.get("new_lines", 0)
    total_lines = stats.get("total_lines", 0)
    last_training = stats.get("last_training")

    # Use new_lines after first training, total_lines before
    lines_for_training = total_lines
    min_required = kraken_training_service.MIN_LINES_FINETUNE if base_model else kraken_training_service.MIN_LINES_SCRATCH

    if lines_for_training < min_required:
        mode = "fine-tuning" if base_model else "training from scratch"
        raise HTTPException(
            status_code=400,
            detail=f"Not enough training data for {mode}. Need at least {min_required} lines, got {lines_for_training}"
        )

    # Generate model name if not provided
    if not model_name:
        from datetime import datetime
        model_name = f"kraken_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Run training in a separate thread to avoid blocking the event loop
    import threading

    def run_training_sync():
        try:
            asyncio.run(kraken_training_service.start_training(
                texts_handler=global_new_text_handler,
                epochs=epochs,
                model_name=model_name,
                base_model=base_model,
                batch_size=batch_size,
                device=device,
                patience=patience,
                project_ids=pids,
            ))
        finally:
            if device != "cpu":
                from services.gpu_lock import release as gpu_release
                gpu_release("kraken_training")

    thread = threading.Thread(target=run_training_sync, daemon=True)
    thread.start()
    return {"message": "Kraken training started", "epochs": epochs, "model_name": model_name, "batch_size": batch_size}


@router.get("/training/kraken/progress")
async def get_kraken_training_progress():
    """Get current Kraken training progress."""
    from services.kraken_training_service import kraken_training_service
    return kraken_training_service.progress.to_dict()


@router.post("/training/kraken/cancel")
async def cancel_kraken_training():
    """Cancel ongoing Kraken training."""
    from services.kraken_training_service import kraken_training_service, TrainingStatus

    if kraken_training_service.progress.status != TrainingStatus.TRAINING:
        raise HTTPException(status_code=400, detail="No training in progress")

    kraken_training_service.cancel_training()
    return {"message": "Training cancelled"}


@router.get("/training/kraken/models")
async def list_kraken_models():
    """List available Kraken trained models."""
    from services.kraken_training_service import kraken_training_service
    models = kraken_training_service.get_models()
    return {"models": models}


@router.get("/training/kraken/active-model")
async def get_kraken_active_model():
    """Get information about the currently active Kraken model."""
    from services.kraken_training_service import kraken_training_service
    return kraken_training_service.get_active_model_info()


@router.post("/training/kraken/models/{model_name}/activate")
async def activate_kraken_model(model_name: str):
    """Set a Kraken model as the active OCR model."""
    from services.kraken_training_service import kraken_training_service

    success = kraken_training_service.activate_model(model_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Kraken model not found: {model_name}")

    return {"message": f"Kraken model {model_name} activated"}


@router.delete("/training/kraken/models/{model_name}")
async def delete_kraken_model(model_name: str):
    """Delete a Kraken model file."""
    from services.kraken_training_service import kraken_training_service

    result = kraken_training_service.delete_model(model_name)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", f"Cannot delete model: {model_name}"))

    return {"message": f"Kraken model {model_name} deleted"}


@router.get("/training/kraken/base-models")
async def get_kraken_base_models():
    """Get list of available base models for Kraken training."""
    from services.kraken_training_service import kraken_training_service

    # Return existing models that can be used as base for fine-tuning
    models = kraken_training_service.get_models()

    base_models = [
        {
            "id": "from_scratch",
            "name": "Train from scratch",
            "description": "No base model - train a new model"
        }
    ]

    for model in models:
        base_models.append({
            "id": model["path"],
            "name": model["name"],
            "description": f"Fine-tune from {model['name']}"
        })

    return {"models": base_models}


# ==========================================
# Qwen3-VL QLoRA Training Endpoints
# ==========================================

@router.get("/training/qwen/status")
async def get_qwen_training_status(project_id: int = None, project_ids: Optional[List[int]] = Query(None)):
    """Get the current training data status for Qwen QLoRA fine-tuning."""
    from services.qwen_training_service import qwen_training_service
    from services.training_common import TrainingStatus

    # Normalise: single project_id → list for consistency
    pids = project_ids or ([project_id] if project_id is not None else None)

    stats = qwen_training_service.get_training_stats(global_new_text_handler, project_ids=pids)
    logging.info(f"Qwen training stats: {stats}")

    previous_lines = stats.get("previous_lines", 0)
    new_lines = stats.get("new_lines", 0)
    total_lines = stats.get("total_lines", 0)
    curated_texts = stats.get("curated_texts", 0)
    last_training = stats.get("last_training")
    required_for_training = qwen_training_service.MIN_LINES

    # Always use total_lines for readiness — retraining with more epochs on same data is valid
    lines_for_progress = total_lines
    progress = min(100, int((lines_for_progress / required_for_training) * 100)) if required_for_training > 0 else 0

    current_training = None
    if qwen_training_service.progress.status != TrainingStatus.IDLE:
        current_training = qwen_training_service.progress.to_dict()

    return {
        "curatedTexts": curated_texts,
        "previousLines": previous_lines,
        "newLines": new_lines,
        "totalLines": total_lines,
        "requiredForNextTraining": required_for_training,
        "progress": progress,
        "isReady": lines_for_progress >= required_for_training,
        "lastTraining": last_training,
        "currentTraining": current_training,
    }


@router.post("/training/qwen/start")
async def start_qwen_training(
    epochs: int = 10,
    model_name: str = None,
    base_model: str = None,
    output_mode: str = "plain",
    device: str = "auto",
    patience: int = 3,
    project_id: int = None,
    project_ids: Optional[List[int]] = Query(None),
):
    """Start Qwen QLoRA fine-tuning, optionally scoped to one or more projects."""
    from services.qwen_training_service import qwen_training_service
    from services.training_common import TrainingStatus
    import asyncio

    # Normalise: single project_id → list for consistency
    pids = project_ids or ([project_id] if project_id is not None else None)

    if qwen_training_service.progress.status == TrainingStatus.TRAINING:
        raise HTTPException(status_code=409, detail="Training already in progress")

    # Check GPU availability
    from services.gpu_lock import acquire as gpu_acquire
    ok, owner = gpu_acquire("qwen_training")
    if not ok:
        raise HTTPException(status_code=409, detail=f"GPU is busy ({owner}). Wait for it to finish or cancel it first.")

    stats = qwen_training_service.get_training_stats(global_new_text_handler, project_ids=pids)
    previous_lines = stats.get("previous_lines", 0)
    new_lines = stats.get("new_lines", 0)
    total_lines = stats.get("total_lines", 0)
    last_training = stats.get("last_training")

    # Always use total_lines — retraining with more epochs on same data is valid
    min_required = qwen_training_service.MIN_LINES

    if total_lines < min_required:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough training data. Need at least {min_required} lines, got {total_lines}"
        )

    # Validate output mode
    valid_modes = qwen_training_service.get_output_modes()
    if output_mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid output_mode '{output_mode}'. Valid: {list(valid_modes.keys())}"
        )

    # Validate base model
    if base_model and base_model not in qwen_training_service.BASE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid base_model '{base_model}'. Valid: {list(qwen_training_service.BASE_MODELS.keys())}"
        )

    if not model_name:
        from datetime import datetime
        model_name = f"qwen_lora_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    import threading
    from services.gpu_lock import release as gpu_release

    def run_training_sync():
        try:
            asyncio.run(qwen_training_service.start_training(
                texts_handler=global_new_text_handler,
                epochs=epochs,
                model_name=model_name,
                base_model=base_model,
                output_mode=output_mode,
                device=device,
                patience=patience,
                project_ids=pids,
            ))
        finally:
            gpu_release("qwen_training")

    thread = threading.Thread(target=run_training_sync, daemon=True)
    thread.start()
    return {
        "message": "Qwen QLoRA training started",
        "epochs": epochs,
        "model_name": model_name,
        "base_model": base_model or qwen_training_service.DEFAULT_BASE_MODEL,
        "output_mode": output_mode,
    }


@router.get("/training/qwen/progress")
async def get_qwen_training_progress():
    """Get current Qwen QLoRA training progress."""
    from services.qwen_training_service import qwen_training_service
    return qwen_training_service.progress.to_dict()


@router.post("/training/qwen/cancel")
async def cancel_qwen_training():
    """Cancel ongoing Qwen QLoRA training."""
    from services.qwen_training_service import qwen_training_service
    from services.training_common import TrainingStatus

    if qwen_training_service.progress.status != TrainingStatus.TRAINING:
        raise HTTPException(status_code=400, detail="No training in progress")

    qwen_training_service.cancel_training()
    return {"message": "Training cancelled"}


@router.get("/training/qwen/models")
async def list_qwen_models():
    """List available Qwen QLoRA adapter models."""
    from services.qwen_training_service import qwen_training_service
    models = qwen_training_service.get_models()
    return {"models": models}


@router.get("/training/qwen/active-model")
async def get_qwen_active_model():
    """Get information about the currently active Qwen adapter."""
    from services.qwen_training_service import qwen_training_service
    return qwen_training_service.get_active_model_info()


@router.post("/training/qwen/models/{model_name}/activate")
async def activate_qwen_model(model_name: str):
    """Set a Qwen QLoRA adapter as the active model."""
    from services.qwen_training_service import qwen_training_service

    success = qwen_training_service.activate_model(model_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Qwen adapter not found: {model_name}")

    return {"message": f"Qwen adapter {model_name} activated"}


@router.delete("/training/qwen/models/{model_name}")
async def delete_qwen_model(model_name: str):
    """Delete a Qwen QLoRA adapter."""
    from services.qwen_training_service import qwen_training_service

    success = qwen_training_service.delete_model(model_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Qwen adapter not found or is active: {model_name}")

    return {"message": f"Qwen adapter {model_name} deleted"}


@router.get("/training/qwen/output-modes")
async def get_qwen_output_modes():
    """Get available output modes for Qwen QLoRA training."""
    from services.qwen_training_service import qwen_training_service
    return {"modes": qwen_training_service.get_output_modes()}


@router.get("/training/qwen/base-models")
async def get_qwen_base_models():
    """Get available Qwen base models for fine-tuning."""
    from services.qwen_training_service import qwen_training_service
    return {"models": qwen_training_service.get_base_models()}


# ================================================================== #
# TrOCR Training Endpoints
# ================================================================== #

@router.get("/training/trocr/status")
async def get_trocr_training_status(project_id: int = None, project_ids: Optional[List[int]] = Query(None)):
    """Get TrOCR training status and data readiness."""
    from services.trocr_training_service import trocr_training_service
    from services.training_common import TrainingStatus

    pids = project_ids or ([project_id] if project_id is not None else None)
    stats = trocr_training_service.get_training_stats(global_new_text_handler, project_ids=pids)

    total_lines = stats.get("total_lines", 0)
    previous_lines = stats.get("previous_lines", 0)
    new_lines = stats.get("new_lines", 0)
    last_training = stats.get("last_training")

    required_for_training = trocr_training_service.MIN_LINES
    lines_for_progress = total_lines
    progress = min(100, int((lines_for_progress / required_for_training) * 100)) if required_for_training > 0 else 0

    current_training = None
    if trocr_training_service.progress.status != TrainingStatus.IDLE:
        current_training = trocr_training_service.progress.to_dict()

    return {
        "curatedTexts": stats.get("curated_texts", 0),
        "previousLines": previous_lines,
        "newLines": new_lines,
        "totalLines": total_lines,
        "requiredForNextTraining": required_for_training,
        "progress": progress,
        "isReady": lines_for_progress >= required_for_training,
        "lastTraining": last_training,
        "currentTraining": current_training,
    }


@router.post("/training/trocr/start")
async def start_trocr_training(
    epochs: int = 30,
    model_name: str = None,
    base_model: str = None,
    device: str = "auto",
    patience: int = 5,
    learning_rate: float = 5e-5,
    freeze_encoder: bool = False,
    project_id: int = None,
    project_ids: Optional[List[int]] = Query(None),
):
    """Start TrOCR fine-tuning, optionally scoped to one or more projects."""
    from services.trocr_training_service import trocr_training_service
    from services.kraken_training_service import kraken_training_service
    from services.training_common import TrainingStatus
    import asyncio

    pids = project_ids or ([project_id] if project_id is not None else None)

    if trocr_training_service.progress.status == TrainingStatus.TRAINING:
        raise HTTPException(status_code=409, detail="TrOCR training already in progress")

    from services.gpu_lock import acquire as gpu_acquire
    ok, owner = gpu_acquire("trocr_training")
    if not ok:
        raise HTTPException(status_code=409, detail=f"GPU is busy ({owner}). Wait for it to finish or cancel it first.")

    stats = trocr_training_service.get_training_stats(global_new_text_handler, project_ids=pids)
    total_lines = stats.get("total_lines", 0)

    if total_lines < trocr_training_service.MIN_LINES:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough training data. Need at least {trocr_training_service.MIN_LINES} lines, got {total_lines}"
        )

    if base_model and base_model not in trocr_training_service.BASE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid base_model '{base_model}'. Valid: {list(trocr_training_service.BASE_MODELS.keys())}"
        )

    if not model_name:
        from datetime import datetime
        model_name = f"trocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    import threading
    from services.gpu_lock import release as gpu_release

    def run_training_sync():
        try:
            asyncio.run(trocr_training_service.start_training(
                texts_handler=global_new_text_handler,
                kraken_training_service=kraken_training_service,
                epochs=epochs,
                model_name=model_name,
                base_model=base_model,
                device=device,
                patience=patience,
                learning_rate=learning_rate,
                freeze_encoder=freeze_encoder,
                project_ids=pids,
            ))
        finally:
            gpu_release("trocr_training")

    thread = threading.Thread(target=run_training_sync, daemon=True)
    thread.start()
    return {
        "message": "TrOCR training started",
        "epochs": epochs,
        "model_name": model_name,
        "base_model": base_model or trocr_training_service.DEFAULT_BASE_MODEL,
        "learning_rate": learning_rate,
        "freeze_encoder": freeze_encoder,
    }


@router.get("/training/trocr/progress")
async def get_trocr_training_progress():
    """Get current TrOCR training progress."""
    from services.trocr_training_service import trocr_training_service
    return trocr_training_service.progress.to_dict()


@router.post("/training/trocr/cancel")
async def cancel_trocr_training():
    """Cancel ongoing TrOCR training."""
    from services.trocr_training_service import trocr_training_service
    from services.training_common import TrainingStatus

    if trocr_training_service.progress.status != TrainingStatus.TRAINING:
        raise HTTPException(status_code=400, detail="No TrOCR training in progress")

    trocr_training_service.cancel_training()
    return {"message": "TrOCR training cancelled"}


@router.get("/training/trocr/models")
async def list_trocr_models():
    """List available TrOCR fine-tuned models."""
    from services.trocr_training_service import trocr_training_service
    return {"models": trocr_training_service.get_models()}


@router.get("/training/trocr/active-model")
async def get_trocr_active_model():
    """Get information about the currently active TrOCR model."""
    from services.trocr_training_service import trocr_training_service
    return trocr_training_service.get_active_model_info()


@router.post("/training/trocr/models/{model_name}/activate")
async def activate_trocr_model(model_name: str):
    """Set a TrOCR fine-tuned model as the active model."""
    from services.trocr_training_service import trocr_training_service
    success = trocr_training_service.activate_model(model_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"TrOCR model not found: {model_name}")
    return {"message": f"TrOCR model {model_name} activated"}


@router.delete("/training/trocr/models/{model_name}")
async def delete_trocr_model(model_name: str):
    """Delete a TrOCR fine-tuned model."""
    from services.trocr_training_service import trocr_training_service
    success = trocr_training_service.delete_model(model_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"TrOCR model not found or is active: {model_name}")
    return {"message": f"TrOCR model {model_name} deleted"}


@router.get("/training/trocr/base-models")
async def get_trocr_base_models():
    """Get available TrOCR base models for fine-tuning."""
    from services.trocr_training_service import trocr_training_service
    return {"models": trocr_training_service.get_base_models()}


@router.post("/training/regenerate")
async def regenerate_training_data():
    """One-time migration: scan all curated texts and persist training data to disk.
    Recovers Kraken data from earlier edit_history entries that were overwritten by VLM curation."""
    result = global_new_text_handler.regenerate_all_training_data()
    return result


# ─── CuReD Dataset Export / Import ───────────────────────────────

@router.get("/export/project/{project_id}")
async def export_project_cured(project_id: int):
    """Export all texts in a project as a CuReD zip (manifest.json + images)."""
    import asyncio
    from starlette.background import BackgroundTask
    from common.global_handlers import global_projects_handler
    from entities.new_text import NewText

    project = global_projects_handler.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    texts_raw = global_new_text_handler._collection.find({"project_id": int(project_id)})
    texts = [NewText.parse_obj(t) for t in texts_raw]
    if not texts:
        raise HTTPException(status_code=404, detail="No texts in project")

    zip_path = await asyncio.to_thread(
        global_new_text_handler.build_cured_export_zip,
        texts, project_id, project.name,
    )

    safe_name = (project.name or str(project_id)).replace(" ", "_")
    filename = f"{safe_name}_cured_export.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: os.unlink(zip_path)),
    )


@router.get("/export/text/{text_id}")
async def export_single_text_cured(text_id: int):
    """Export a single text as a CuReD zip (manifest.json + image)."""
    import asyncio
    from starlette.background import BackgroundTask
    from entities.new_text import NewText

    text_doc = global_new_text_handler._collection.find_one({"text_id": int(text_id)})
    if not text_doc:
        raise HTTPException(status_code=404, detail=f"Text {text_id} not found")

    text = NewText.parse_obj(text_doc)
    zip_path = await asyncio.to_thread(
        global_new_text_handler.build_cured_export_zip,
        [text], text.project_id, None,
    )

    identifier = text.museum_id or text.p_number or text.publication_id or str(text_id)
    safe_id = identifier.replace("/", "_").replace(" ", "_")
    filename = f"{safe_id}_{text_id}_cured_export.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: os.unlink(zip_path)),
    )


@router.post("/import")
async def import_cured_zip(
    file: UploadFile = File(...),
    project_id: Optional[int] = Form(None),
):
    """Import a CuReD export zip. Recreates texts with images and transliterations.
    If is_curated_kraken is set, Kraken training data is auto-generated on import."""
    import asyncio
    import tempfile

    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        tmp.write(await file.read())
        tmp.close()
        result = await asyncio.to_thread(
            global_new_text_handler.import_cured_zip,
            tmp.name, project_id,
        )
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

    if result.get("errors") and result["imported"] == 0:
        raise HTTPException(status_code=400, detail=f"Import failed: {result['errors']}")

    return result


class ImportFolderDto(BaseModel):
    folder_path: str
    project_id: Optional[int] = None


@router.post("/import-folder")
async def import_cured_folder(dto: ImportFolderDto):
    """Import CuReD data from an unzipped local folder containing manifest.json + images/.
    Used when the export was already extracted or shared as a folder."""
    import asyncio

    if not os.path.isdir(dto.folder_path):
        raise HTTPException(status_code=400, detail=f"Folder not found: {dto.folder_path}")

    manifest_path = os.path.join(dto.folder_path, "manifest.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="manifest.json not found in folder")

    result = await asyncio.to_thread(
        global_new_text_handler.import_cured_folder,
        dto.folder_path, dto.project_id,
    )

    if result.get("errors") and result["imported"] == 0:
        raise HTTPException(status_code=400, detail=f"Import failed: {result['errors']}")

    return result


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
        is_curated_kraken=submit_dto.is_curated_kraken,
        is_curated_vlm=submit_dto.is_curated_vlm,
        training_targets=submit_dto.training_targets,
    )

    transliteration_id = global_new_text_handler.save_new_transliteration(dto=submit_dto, uploader_id=user_id)
    return transliteration_id


@router.post("/saveImage/")
async def save_text_image(request: Request, file: UploadFile = File(...), text_id=Form(...)):
    StorageUtils.validate_image_file_type(file=file)

    import glob
    train_dir = os.path.join(StorageUtils.BASE_PATH, StorageUtils.CURED_TRAINING_DATA_DIR_NAME)
    preview_dir = os.path.join(StorageUtils.BASE_PATH, StorageUtils.PREVIEW_DIR_NAME)

    # Delete any existing images for this text (old crops, etc.)
    existing = glob.glob(os.path.join(train_dir, f"{text_id}_*"))
    for old_file in existing:
        logging.info(f"Deleting old image: {old_file}")
        os.remove(old_file)
    for old_preview in glob.glob(os.path.join(preview_dir, f"{text_id}_*")):
        os.remove(old_preview)

    # Generate a fresh name with the correct extension
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
        raise HTTPException(status_code=400, detail="Invalid file type. Expected PDF.")

    try:
        pdf_bytes = await raw_pdf.read()
        page_png_bytes = PdfUtils.extract_page_as_png(pdf_bytes=pdf_bytes, page=page)
        temp_file, temp_file_path = StorageUtils.create_temp_file()
        try:
            StorageUtils.write_to_file(file=temp_file, content=page_png_bytes)
        finally:
            background_tasks.add_task(StorageUtils.delete_file, temp_file_path)

        return FileResponse(temp_file_path)
    except RuntimeError as e:
        # Poppler not found or other configuration error
        logging.error(f"PDF conversion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logging.error(f"PDF conversion failed: {e}")
        raise HTTPException(status_code=500, detail=f"PDF conversion failed: {str(e)}")


@router.get("/{ben_id}/transliterations")
async def get_text_transliterations(ben_id: int):
    if type(ben_id) is not int:
        raise HTTPException(status_code=500, detail="invalid BEN id")

    return global_new_text_handler.get_text_cured_transliterations_preview(ben_id)


@router.post("/getTransliterations")
async def get_transliterations(background_tasks: BackgroundTasks, dto: CureDGetTransliterationsDto):
    logging.info(f"getTransliterations called with model: {dto.model}")
    result = CuredHandler.get_transliterations(dto=dto, background_tasks=background_tasks)
    logging.info(f"getTransliterations returning {len(result.lines)} lines")
    return result


# ─── Line Detection (Segmentation Only) ──────────────────────────


class DetectLinesDto(BaseModel):
    image: str  # base64 image


@router.post("/detectLines")
async def detect_lines(dto: DetectLinesDto):
    """
    Run Kraken line segmentation on the image (no OCR).
    Returns bounding boxes only. Fast, CPU-only, no model required.
    Use this to add boxes to VLM OCR results for training data preparation.
    """
    from clients.kraken_client import KrakenOcrClient

    # Strip data URL prefix if present
    image_base64 = dto.image
    if image_base64.startswith("data:"):
        comma_idx = image_base64.find(",")
        if comma_idx != -1:
            image_base64 = image_base64[comma_idx + 1:]

    result = KrakenOcrClient.segment_image(image_base64)
    boxes = result.get("dimensions", [])
    error = result.get("error")

    logging.info(f"detectLines: {len(boxes)} boxes detected")
    if error:
        logging.error(f"detectLines error: {error}")

    return {"dimensions": boxes, "error": error}


# ─── TEI Lex-0 Validation ─────────────────────────────────────────

from pydantic import BaseModel as PydanticBaseModel
from typing import Optional, List, Dict, Any


class ValidateTeiDto(PydanticBaseModel):
    xml: str


class RetryTeiDto(PydanticBaseModel):
    xml: str
    errors: List[Dict[str, Any]] = []
    provider: str = "gemini"
    apiKey: Optional[str] = None


@router.post("/validate-tei")
async def validate_tei(dto: ValidateTeiDto):
    """Validate a TEI Lex-0 <entry> element against XSD + custom rules."""
    from services.tei_lex0_validator import tei_lex0_validator
    result = tei_lex0_validator.validate_entry(dto.xml)
    return result


@router.post("/retry-tei")
async def retry_tei_entry(dto: RetryTeiDto):
    """
    Retry a failed TEI entry with a correction prompt via VLM.
    Sends the correction prompt (with previous XML + errors) to the specified provider.
    """
    from services.tei_prompt_builder import tei_prompt_builder
    from services.tei_converter import tei_converter
    from clients.ocr_factory import OCRFactory

    correction_prompt = tei_prompt_builder.build_correction_prompt(dto.xml, dto.errors)

    try:
        # Use the OCR client to send correction prompt (text-only, no image)
        ocr_client = OCRFactory.get_client(provider_name=dto.provider, api_key=dto.apiKey)

        # Most VLM clients accept a prompt parameter — send correction as the prompt
        # with a minimal 1x1 white image (some clients require an image)
        import base64
        from io import BytesIO
        from PIL import Image
        buf = BytesIO()
        Image.new("RGB", (1, 1), "white").save(buf, format="PNG")
        dummy_image = base64.b64encode(buf.getvalue()).decode("utf-8")

        result = ocr_client.ocr_image(
            image_base64=dummy_image,
            image_width=1,
            image_height=1,
            prompt=correction_prompt,
        )

        corrected_xml = result.get("text", "")

        # Validate the corrected entry
        validated = tei_converter.validate_single(corrected_xml)
        return validated

    except Exception as e:
        logging.error(f"TEI retry failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/transliteration/{text_id}/{transliteration_id}")
async def fetch_transliteration_by_id(text_id: int, transliteration_id: int):
    if type(text_id) is not int or type(transliteration_id) is not int:
        raise HTTPException(status_code=500, detail="invalid BEN / transliteration id")

    transliterations = global_new_text_handler.get_text_cured_transliterations(text_id=text_id)
    trans = next((trans for trans in transliterations if trans.transliteration_id == transliteration_id), None)
    if not trans:
        raise HTTPException(status_code=404, detail="Transliteration not found")

    result = CuredTransliterationData.from_transliteration_entity(entity=trans)
    if result is None:
        raise HTTPException(status_code=404, detail="Transliteration has no saved content (empty edit history)")

    return result


@router.get("/transliterationImage/{text_id}/{transliteration_id}")
async def get_image(text_id: int, transliteration_id: int):
    import glob
    if type(text_id) is not int or type(transliteration_id) is not int:
        raise HTTPException(status_code=500, detail="invalid BEN / transliteration id")

    transliterations = global_new_text_handler.get_text_cured_transliterations(text_id=text_id)
    trans = next((t for t in transliterations if t.transliteration_id == transliteration_id), None)
    if not trans:
        raise HTTPException(status_code=500, detail="Transliteration doesn't exist")

    image_name = trans.image_name
    image_path = None

    # Try the stored image_name first
    if image_name:
        image_path = StorageUtils.build_cured_train_image_path(image_name=image_name)
        if not os.path.isfile(image_path):
            image_path = None

    # Fallback: find any image file matching this text_id
    if not image_path:
        train_dir = os.path.join(StorageUtils.BASE_PATH, StorageUtils.CURED_TRAINING_DATA_DIR_NAME)
        matches = glob.glob(os.path.join(train_dir, f"{text_id}_*"))
        if matches:
            image_path = matches[0]
            # Fix the DB record so this doesn't happen again
            found_name = os.path.basename(image_path)
            logging.info(f"Image fallback: updating image_name from '{image_name}' to '{found_name}' for text {text_id}")
            global_new_text_handler.update_transliteration_image(text_id, transliteration_id, found_name)

    if not image_path:
        raise HTTPException(status_code=404, detail="No image found for this transliteration")

    return FileResponse(image_path, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    })


class BatchDeleteDto(BaseModel):
    text_ids: List[int]


class RemoveTileMarkersDto(BaseModel):
    project_id: Optional[int] = None
    text_ids: Optional[List[int]] = None


@router.post("/remove-tile-markers")
async def remove_tile_markers(dto: RemoveTileMarkersDto):
    """Remove ************************ tile merge marker lines from texts."""
    import asyncio
    result = await asyncio.to_thread(
        global_new_text_handler.remove_tile_markers,
        project_id=dto.project_id,
        text_ids=dto.text_ids,
    )
    return result


@router.post("/batch-delete")
async def batch_delete_texts(dto: BatchDeleteDto):
    """Delete multiple texts in a single operation (much faster than individual deletes)."""
    import asyncio
    if not dto.text_ids:
        return {"deleted": 0, "errors": []}
    result = await asyncio.to_thread(global_new_text_handler.delete_texts_batch, dto.text_ids)
    return result


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
