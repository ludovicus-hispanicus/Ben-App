"""
YOLO Training API Router - Endpoints for YOLO layout detection training and inference.
"""

from typing import List
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
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
    # Auto-Annotate DTOs
    AutoAnnotateRequest,
    AutoAnnotateStatusResponse,
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


@router.put("/datasets/{dataset_name}/metadata")
async def update_dataset_metadata(request: Request, dataset_name: str, body: dict):
    """
    Update dataset name, description, and/or curated flag.

    Body: { "name": "new name", "description": "new description", "curated": true }
    All fields are optional.
    """
    result = yolo_training_handler.update_dataset_metadata(
        dataset_name,
        name=body.get("name"),
        description=body.get("description"),
        curated=body.get("curated"),
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.post("/datasets/{dataset_name}/classes")
async def add_classes_to_dataset(request: Request, dataset_name: str, body: dict):
    """
    Add new classes to an existing dataset.

    Body: { "classes": ["pagenumber", "root_index"] }
    Or with colors: { "classes": [{"name": "pagenumber", "color": "#FF6600"}] }
    Skips classes that already exist. Updates metadata.json, dataset.yaml, and labels.txt.
    """
    new_classes = body.get("classes", [])
    if not new_classes:
        raise HTTPException(status_code=400, detail="No classes provided")

    result = yolo_training_handler.add_classes_to_dataset(dataset_name, new_classes)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.put("/datasets/{dataset_name}/classes/{class_id}/color")
async def update_class_color(request: Request, dataset_name: str, class_id: int, body: dict):
    """
    Update the color of an existing class in a dataset.

    Body: { "color": "#FF6600" }
    """
    color = body.get("color")
    if not color:
        raise HTTPException(status_code=400, detail="No color provided")

    result = yolo_training_handler.update_class_color(dataset_name, class_id, color)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.put("/datasets/{dataset_name}/classes/{class_id}/name")
async def rename_class(request: Request, dataset_name: str, class_id: int, body: dict):
    """
    Rename an existing class in a dataset.

    Body: { "name": "new_class_name" }
    Updates metadata.json, dataset.yaml, and labels.txt.
    """
    new_name = body.get("name")
    if not new_name or not new_name.strip():
        raise HTTPException(status_code=400, detail="No name provided")

    result = yolo_training_handler.rename_class(dataset_name, class_id, new_name.strip())

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

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


@router.put("/datasets/{dataset_name}/images/{image_id}/curated")
async def toggle_image_curated(request: Request, dataset_name: str, image_id: str, body: dict):
    """
    Mark or unmark an image as curated (reviewed).

    Body: { "curated": true }
    """
    curated = body.get("curated", True)
    result = yolo_training_handler.toggle_image_curated(dataset_name, image_id, curated)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("message", "Failed"))

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


# ============== Dataset Merge Endpoint ==============

@router.post("/datasets/merge")
async def merge_datasets(request: Request):
    """
    Merge multiple datasets into a new one. Originals stay untouched.
    Classes are merged by name; label class IDs are remapped.

    Body:
        source_datasets: list of dataset names to merge
        target_name: name for the new merged dataset
        description: optional description
    """
    body = await request.json()
    source_datasets = body.get("source_datasets", [])
    target_name = body.get("target_name", "")
    description = body.get("description")

    if not source_datasets or not target_name:
        raise HTTPException(status_code=400, detail="source_datasets and target_name are required")

    result = await asyncio.to_thread(
        yolo_training_handler.merge_datasets, source_datasets, target_name, description
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Merge failed"))

    return result


# ============== Dataset Export Endpoints ==============

@router.get("/datasets/{dataset_name}/download")
async def download_dataset(dataset_name: str, format: str = "training"):
    """
    Download a dataset as a zip file.

    Query params:
        format: "training" (YOLO format with images + labels + yaml)
                or "snippets" (cropped bounding boxes organized by page, with manifest.json)
    """
    if format not in ("training", "snippets"):
        raise HTTPException(status_code=400, detail="format must be 'training' or 'snippets'")

    try:
        zip_path = await asyncio.to_thread(
            yolo_training_handler.export_dataset, dataset_name, format
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

    filename = f"{dataset_name}_{format}.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: __import__("os").unlink(zip_path)),
    )


@router.post("/datasets/{dataset_name}/save-to-library")
async def save_snippets_to_library(
    dataset_name: str,
    project_id: str = None,
    project_name: str = None,
):
    """
    Save dataset snippets directly to the Pages library.

    Instead of downloading a ZIP, this crops all annotated regions and saves them
    as pages in a Pages project, along with a manifest.json.

    Query params:
        project_id: Existing project to save into (optional)
        project_name: Name for new project (optional, defaults to {dataset_name}_snippets)
    """
    try:
        result = await asyncio.to_thread(
            yolo_training_handler.save_snippets_to_library,
            dataset_name, project_id, project_name
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save to library failed: {str(e)}")

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


@router.get("/models/active")
async def get_active_model():
    """Get the currently active YOLO model."""
    return await yolo_training_handler.get_active_model()


@router.post("/models/{model_name}/activate")
async def activate_model(model_name: str):
    """Set a trained model as the active/default model."""
    result = await yolo_training_handler.activate_model(model_name)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Activation failed"))

    return result


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


@router.get("/train/jobs")
async def list_training_jobs(request: Request, limit: int = 20):
    """
    List recent training jobs.
    """
    user_id = getattr(request.state, 'user_id', None)
    return yolo_training_handler.list_training_jobs(user_id=user_id, limit=limit)


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


@router.get("/train/{training_id}/logs")
async def get_training_logs(request: Request, training_id: str):
    """
    Get training logs (per-epoch metrics from results.csv).
    """
    result = await asyncio.to_thread(yolo_training_handler.get_training_logs, training_id)
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
            yield f"data: {json.dumps(progress.dict() if hasattr(progress, 'dict') else progress, default=str)}\n\n"

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


# ============== Auto-Annotate Endpoints ==============

@router.post("/auto-annotate")
async def start_auto_annotate(request: Request, body: AutoAnnotateRequest):
    """
    Start an auto-annotation job.

    Creates a new dataset by running model predictions on all images
    in a source project. The resulting dataset can be reviewed and
    corrected in the annotation canvas before retraining.
    """
    user_id = getattr(request.state, 'user_id', None)

    result = await yolo_training_handler.start_auto_annotate(
        source_project_id=body.source_project_id,
        model_name=body.model_name,
        dataset_name=body.dataset_name,
        confidence=body.confidence,
        iou=body.iou,
        val_ratio=body.val_ratio,
        user_id=user_id,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/auto-annotate/{job_id}/status", response_model=AutoAnnotateStatusResponse)
async def get_auto_annotate_status(request: Request, job_id: str):
    """
    Get the current status of an auto-annotation job.

    Returns progress (images processed / total) and detection counts.
    """
    result = yolo_training_handler.get_auto_annotate_status(job_id)

    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Job not found"))

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
