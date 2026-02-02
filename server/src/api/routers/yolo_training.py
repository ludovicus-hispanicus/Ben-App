"""
YOLO Training API Router - Endpoints for YOLO layout detection training and inference.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
import asyncio
import json

from handlers.yolo_training_handler import yolo_training_handler
from api.dto.yolo_training import (
    # Dataset DTOs
    DatasetCreateRequest,
    DatasetCreateResponse,
    ImageUploadRequest,
    ImageUploadResponse,
    DatasetStatsResponse,
    DatasetListItem,
    # Model DTOs
    ModelListResponse,
    ModelInfo,
    # Training DTOs
    TrainingStartRequest,
    TrainingStartResponse,
    TrainingStatusResponse,
    TrainingConfig,
    # Inference DTOs
    PredictRequest,
    PredictResponse,
)

router = APIRouter(prefix="/api/v1/yolo", tags=["yolo-training"])


# ============== Dataset Endpoints ==============

@router.post("/datasets", response_model=DatasetCreateResponse)
async def create_dataset(request: Request, body: DatasetCreateRequest):
    """
    Create a new YOLO dataset for training.

    Creates the directory structure and configuration files needed for YOLO training.
    """
    result = yolo_training_handler.create_dataset(
        name=body.name,
        classes=body.classes,
        description=body.description
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/datasets", response_model=List[DatasetListItem])
async def list_datasets(request: Request):
    """
    List all available datasets.
    """
    return yolo_training_handler.list_datasets()


@router.get("/datasets/{dataset_name}/stats", response_model=DatasetStatsResponse)
async def get_dataset_stats(request: Request, dataset_name: str):
    """
    Get statistics about a dataset including class distribution and training readiness.
    """
    result = yolo_training_handler.get_dataset_stats(dataset_name)

    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.post("/datasets/{dataset_name}/images", response_model=ImageUploadResponse)
async def upload_image(
    request: Request,
    dataset_name: str,
    body: ImageUploadRequest
):
    """
    Upload an image with annotations to a dataset.

    The image should be base64 encoded. Annotations should be in YOLO format
    (normalized coordinates: x_center, y_center, width, height all between 0 and 1).
    """
    result = yolo_training_handler.add_image(
        dataset_name=dataset_name,
        image_base64=body.image,
        filename=body.filename,
        annotations=[a.dict() for a in body.annotations],
        split=body.split
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.delete("/datasets/{dataset_name}")
async def delete_dataset(request: Request, dataset_name: str):
    """
    Delete a dataset and all its images/annotations.
    """
    result = yolo_training_handler.delete_dataset(dataset_name)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/datasets/{dataset_name}/images")
async def list_dataset_images(request: Request, dataset_name: str):
    """
    List all images in a dataset with their annotation counts.

    Returns images grouped by whether they have annotations or not.
    Useful for identifying images that were saved without annotations.
    """
    result = yolo_training_handler.list_dataset_images(dataset_name)

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", "Dataset not found"))

    return result


@router.get("/datasets/{dataset_name}/images/{image_id}")
async def get_dataset_image(request: Request, dataset_name: str, image_id: str, split: str = None):
    """
    Get a specific image with its annotations from a dataset.

    Returns the image as base64 along with its annotations in YOLO format.
    Useful for reviewing/editing existing annotations.
    """
    result = yolo_training_handler.get_dataset_image(dataset_name, image_id, split)

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", "Image not found"))

    return result


@router.put("/datasets/{dataset_name}/images/{image_id}")
async def update_image_annotations(request: Request, dataset_name: str, image_id: str, body: dict):
    """
    Update annotations for an existing image in a dataset.

    Body should contain:
    - annotations: List of annotation objects with class_id, x_center, y_center, width, height
    - split: Optional split to search in (train or val)
    """
    annotations = body.get("annotations", [])
    split = body.get("split")

    result = yolo_training_handler.update_image_annotations(dataset_name, image_id, annotations, split)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.delete("/datasets/{dataset_name}/images/{image_id}")
async def delete_dataset_image(request: Request, dataset_name: str, image_id: str):
    """
    Delete a specific image and its label file from a dataset.
    """
    result = yolo_training_handler.delete_dataset_image(dataset_name, image_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.post("/datasets/{dataset_name}/cleanup")
async def cleanup_empty_images(request: Request, dataset_name: str):
    """
    Remove all images that have no annotations (empty label files).

    Use this to clean up datasets after accidentally saving images without annotations.
    Returns the list of removed images.
    """
    result = yolo_training_handler.cleanup_empty_images(dataset_name)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


# ============== Model Endpoints ==============

@router.get("/models", response_model=ModelListResponse)
async def list_models(request: Request):
    """
    List all trained models and available base models.

    Returns:
    - models: List of trained models with metrics and metadata
    - base_models: List of base models that can be used for training
    """
    return yolo_training_handler.list_models()


@router.delete("/models/{model_name}")
async def delete_model(request: Request, model_name: str):
    """
    Delete a trained model.
    """
    result = yolo_training_handler.delete_model(model_name)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


# ============== Training Endpoints ==============

@router.post("/train", response_model=TrainingStartResponse)
async def start_training(request: Request, body: TrainingStartRequest):
    """
    Start a training job.

    Training runs asynchronously. Use the returned training_id to track progress
    via the /train/{training_id}/status endpoint.

    Parameters:
    - dataset_name: Name of the dataset to train on
    - base_model: Base model to fine-tune (e.g., 'yolov8s.pt' or 'ahw_v1/best.pt')
    - output_name: Name for the trained model
    - config: Training configuration (epochs, batch_size, etc.)
    """
    user_id = getattr(request.state, 'user_id', None)

    result = await yolo_training_handler.start_training(
        dataset_name=body.dataset_name,
        output_name=body.output_name,
        base_model=body.base_model,
        config=body.config,
        user_id=user_id
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/train/{training_id}/status", response_model=TrainingStatusResponse)
async def get_training_status(request: Request, training_id: str):
    """
    Get the current status of a training job.

    Returns progress information including current epoch, metrics, and any errors.
    """
    result = yolo_training_handler.get_training_status(training_id)

    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", "Training job not found"))

    return result


@router.get("/train/{training_id}/stream")
async def stream_training_status(request: Request, training_id: str):
    """
    Stream training status updates via Server-Sent Events (SSE).

    Connect to this endpoint to receive real-time progress updates during training.
    """
    async def event_generator():
        while True:
            result = yolo_training_handler.get_training_status(training_id)

            if not result["success"]:
                yield f"data: {json.dumps({'error': 'Training job not found'})}\n\n"
                break

            progress = result["progress"]
            yield f"data: {json.dumps(progress.dict() if hasattr(progress, 'dict') else progress)}\n\n"

            # Stop streaming if training is complete
            if progress.status in ["completed", "failed", "cancelled"]:
                break

            await asyncio.sleep(2)  # Update every 2 seconds

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.get("/train/jobs")
async def list_training_jobs(request: Request, limit: int = 20):
    """
    List recent training jobs.
    """
    user_id = getattr(request.state, 'user_id', None)
    return yolo_training_handler.list_training_jobs(user_id=user_id, limit=limit)


@router.post("/train/{training_id}/cancel")
async def cancel_training(request: Request, training_id: str):
    """
    Cancel a pending training job.

    Note: Running jobs cannot be cancelled without restarting the server.
    """
    result = yolo_training_handler.cancel_training(training_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


# ============== Inference Endpoints ==============

@router.post("/predict", response_model=PredictResponse)
async def predict(request: Request, body: PredictRequest):
    """
    Run layout detection on an image.

    Parameters:
    - image: Base64 encoded image
    - model: Model name to use ('default' uses the most recently trained model)
    - confidence: Confidence threshold (0-1)
    - iou: IoU threshold for non-maximum suppression
    """
    result = await yolo_training_handler.predict(
        image_base64=body.image,
        model_name=body.model,
        confidence=body.confidence,
        iou=body.iou
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Prediction failed"))

    return result


# ============== Health Check ==============

@router.get("/health")
async def health_check():
    """
    Check if the YOLO service is healthy.
    """
    try:
        # Try to list models (quick operation)
        models = yolo_training_handler.list_models()
        return {
            "status": "healthy",
            "models_count": len(models.get("models", [])),
            "datasets_count": len(yolo_training_handler.list_datasets()),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }
