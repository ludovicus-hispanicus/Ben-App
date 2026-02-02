"""
YOLO Training Handler - Business logic for YOLO training and inference.
Manages training jobs, provides progress tracking, and coordinates with the YOLO client.
"""

import asyncio
import logging
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor

from clients.yolo_training_client import yolo_training_client, DATASETS_PATH, MODELS_PATH
from mongo.mongo_client import MongoClient
from api.dto.yolo_training import (
    TrainingStatus,
    TrainingConfig,
    TrainingProgress,
)

logger = logging.getLogger(__name__)


class YoloTrainingHandler:
    """Handler for YOLO training operations with async job management."""

    TRAINING_JOBS_COLLECTION = "yolo_training_jobs"

    def __init__(self):
        self._db = MongoClient.get_db()
        self._active_jobs: Dict[str, Dict] = {}
        self._executor = ThreadPoolExecutor(max_workers=2)  # Limit concurrent training

    # ============== Dataset Operations ==============

    def create_dataset(self, name: str, classes: List[str], description: str = None) -> Dict:
        """Create a new dataset."""
        try:
            result = yolo_training_client.create_dataset(name, classes, description)
            return {
                "success": True,
                "dataset_id": result["dataset_id"],
                "name": result["name"],
                "classes": result["classes"],
                "message": f"Dataset '{name}' created successfully",
            }
        except ValueError as e:
            return {
                "success": False,
                "dataset_id": None,
                "name": name,
                "classes": [],
                "message": str(e),
            }

    def add_image(
        self,
        dataset_name: str,
        image_base64: str,
        filename: str,
        annotations: List[Dict],
        split: str = "train"
    ) -> Dict:
        """Add an image with annotations to a dataset."""
        try:
            result = yolo_training_client.add_image_to_dataset(
                dataset_name, image_base64, filename, annotations, split
            )
            return {
                "success": True,
                "image_id": result["image_id"],
                "filename": result["filename"],
                "annotation_count": result["annotation_count"],
                "message": f"Image added to {split} set",
            }
        except ValueError as e:
            return {
                "success": False,
                "image_id": None,
                "filename": filename,
                "annotation_count": 0,
                "message": str(e),
            }

    def get_dataset_stats(self, dataset_name: str) -> Dict:
        """Get dataset statistics."""
        try:
            return yolo_training_client.get_dataset_stats(dataset_name)
        except ValueError as e:
            return {
                "dataset_id": dataset_name,
                "name": dataset_name,
                "error": str(e),
                "ready_for_training": False,
                "issues": [str(e)],
            }

    def list_datasets(self) -> List[Dict]:
        """List all datasets."""
        return yolo_training_client.list_datasets()

    def delete_dataset(self, dataset_name: str) -> Dict:
        """Delete a dataset."""
        try:
            yolo_training_client.delete_dataset(dataset_name)
            return {"success": True, "message": f"Dataset '{dataset_name}' deleted"}
        except ValueError as e:
            return {"success": False, "message": str(e)}

    def list_dataset_images(self, dataset_name: str) -> Dict:
        """List all images in a dataset."""
        try:
            images = yolo_training_client.list_dataset_images(dataset_name)
            return {
                "success": True,
                "images": images,
                "total": len(images),
                "with_annotations": len([i for i in images if i["has_annotations"]]),
                "without_annotations": len([i for i in images if not i["has_annotations"]]),
            }
        except ValueError as e:
            return {"success": False, "images": [], "error": str(e)}

    def get_dataset_image(self, dataset_name: str, image_id: str, split: str = None) -> Dict:
        """Get a specific image with its annotations from a dataset."""
        try:
            result = yolo_training_client.get_dataset_image(dataset_name, image_id, split)
            return {"success": True, **result}
        except ValueError as e:
            return {"success": False, "error": str(e)}

    def update_image_annotations(self, dataset_name: str, image_id: str, annotations: List[Dict], split: str = None) -> Dict:
        """Update annotations for an existing image in a dataset."""
        try:
            result = yolo_training_client.update_image_annotations(dataset_name, image_id, annotations, split)
            return {
                "success": True,
                "image_id": result["image_id"],
                "split": result["split"],
                "annotation_count": result["annotation_count"],
                "message": f"Updated {result['annotation_count']} annotations",
            }
        except ValueError as e:
            return {"success": False, "message": str(e)}

    def delete_dataset_image(self, dataset_name: str, image_id: str) -> Dict:
        """Delete a specific image from a dataset."""
        try:
            yolo_training_client.delete_dataset_image(dataset_name, image_id)
            return {"success": True, "message": f"Image '{image_id}' deleted"}
        except ValueError as e:
            return {"success": False, "message": str(e)}

    def cleanup_empty_images(self, dataset_name: str) -> Dict:
        """Remove all images without annotations from a dataset."""
        try:
            result = yolo_training_client.cleanup_empty_images(dataset_name)
            return {
                "success": True,
                "removed_count": result["removed_count"],
                "removed_images": result["removed_images"],
                "message": f"Removed {result['removed_count']} images without annotations",
            }
        except ValueError as e:
            return {"success": False, "removed_count": 0, "message": str(e)}

    # ============== Model Operations ==============

    def list_models(self) -> Dict:
        """List all models."""
        result = yolo_training_client.list_models()
        return {
            "success": True,
            "models": result["models"],
            "base_models": result["base_models"],
        }

    def delete_model(self, model_name: str) -> Dict:
        """Delete a model."""
        try:
            yolo_training_client.delete_model(model_name)
            return {"success": True, "message": f"Model '{model_name}' deleted"}
        except ValueError as e:
            return {"success": False, "message": str(e)}

    # ============== Training Operations ==============

    async def start_training(
        self,
        dataset_name: str,
        output_name: str,
        base_model: str,
        config: TrainingConfig,
        user_id: str = None
    ) -> Dict:
        """
        Start a training job asynchronously.

        Returns immediately with a training_id that can be used to track progress.
        """
        # Validate dataset exists and is ready
        stats = self.get_dataset_stats(dataset_name)
        if not stats.get("ready_for_training", False):
            return {
                "success": False,
                "training_id": None,
                "message": f"Dataset not ready: {stats.get('issues', ['Unknown issue'])}",
            }

        # Check if output name already exists
        models = yolo_training_client.list_models()
        if any(m["model_id"] == output_name for m in models["models"]):
            return {
                "success": False,
                "training_id": None,
                "message": f"Model '{output_name}' already exists. Choose a different name or delete the existing model.",
            }

        # Create training job record
        training_id = str(uuid.uuid4())[:8]
        job_record = {
            "_id": training_id,
            "training_id": training_id,
            "dataset_name": dataset_name,
            "output_name": output_name,
            "base_model": base_model,
            "config": config.dict() if hasattr(config, 'dict') else config,
            "status": TrainingStatus.PENDING.value,
            "current_epoch": 0,
            "total_epochs": config.epochs if hasattr(config, 'epochs') else config.get("epochs", 100),
            "progress_percent": 0,
            "metrics": None,
            "error": None,
            "user_id": user_id,
            "created_at": datetime.utcnow(),
            "started_at": None,
            "completed_at": None,
        }

        # Save to database
        self._db[self.TRAINING_JOBS_COLLECTION].insert_one(job_record)

        # Track active job
        self._active_jobs[training_id] = job_record

        # Start training in background thread
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            self._executor,
            self._run_training,
            training_id,
            dataset_name,
            output_name,
            base_model,
            config.dict() if hasattr(config, 'dict') else config,
        )

        logger.info(f"Started training job {training_id}: {dataset_name} -> {output_name}")

        return {
            "success": True,
            "training_id": training_id,
            "message": f"Training job started. Use training_id to track progress.",
        }

    def _run_training(
        self,
        training_id: str,
        dataset_name: str,
        output_name: str,
        base_model: str,
        config: Dict
    ):
        """Run training in a background thread."""
        try:
            # Update status to running
            self._update_job_status(training_id, TrainingStatus.RUNNING, started_at=datetime.utcnow())

            # Run training (this blocks)
            result = yolo_training_client.train_model(
                dataset_name=dataset_name,
                output_name=output_name,
                base_model=base_model,
                config=config,
            )

            # Update status to completed
            self._update_job_status(
                training_id,
                TrainingStatus.COMPLETED,
                completed_at=datetime.utcnow(),
                metrics=result.get("metrics"),
                progress_percent=100,
                current_epoch=config.get("epochs", 100),
            )

            logger.info(f"Training job {training_id} completed successfully")

        except Exception as e:
            logger.error(f"Training job {training_id} failed: {str(e)}")
            self._update_job_status(
                training_id,
                TrainingStatus.FAILED,
                error=str(e),
                completed_at=datetime.utcnow(),
            )

        finally:
            # Remove from active jobs
            if training_id in self._active_jobs:
                del self._active_jobs[training_id]

    def _update_job_status(self, training_id: str, status: TrainingStatus, **kwargs):
        """Update a training job's status in the database."""
        update = {"status": status.value}
        update.update(kwargs)

        self._db[self.TRAINING_JOBS_COLLECTION].update_one(
            {"_id": training_id},
            {"$set": update}
        )

        # Also update active jobs dict
        if training_id in self._active_jobs:
            self._active_jobs[training_id].update(update)

    def get_training_status(self, training_id: str) -> Dict:
        """Get the current status of a training job."""
        # Check active jobs first (more up-to-date)
        if training_id in self._active_jobs:
            job = self._active_jobs[training_id]
        else:
            # Check database
            job = self._db[self.TRAINING_JOBS_COLLECTION].find_one({"_id": training_id})

        if not job:
            return {
                "success": False,
                "progress": None,
                "error": f"Training job '{training_id}' not found",
            }

        progress = TrainingProgress(
            training_id=training_id,
            status=TrainingStatus(job.get("status", "pending")),
            current_epoch=job.get("current_epoch", 0),
            total_epochs=job.get("total_epochs", 100),
            progress_percent=job.get("progress_percent", 0),
            metrics=job.get("metrics"),
            eta_seconds=job.get("eta_seconds"),
            error=job.get("error"),
            started_at=job.get("started_at"),
            completed_at=job.get("completed_at"),
        )

        return {
            "success": True,
            "progress": progress,
        }

    def list_training_jobs(self, user_id: str = None, limit: int = 20) -> List[Dict]:
        """List recent training jobs."""
        query = {}
        if user_id:
            query["user_id"] = user_id

        jobs = list(
            self._db[self.TRAINING_JOBS_COLLECTION]
            .find(query)
            .sort("created_at", -1)
            .limit(limit)
        )

        return [
            {
                "training_id": job["_id"],
                "dataset_name": job.get("dataset_name"),
                "output_name": job.get("output_name"),
                "status": job.get("status"),
                "progress_percent": job.get("progress_percent", 0),
                "created_at": job.get("created_at"),
                "completed_at": job.get("completed_at"),
            }
            for job in jobs
        ]

    def cancel_training(self, training_id: str) -> Dict:
        """Cancel a running training job."""
        # Note: Actually stopping a running YOLO training requires more complex handling
        # For now, we just mark it as cancelled if it's pending
        job = self._db[self.TRAINING_JOBS_COLLECTION].find_one({"_id": training_id})

        if not job:
            return {"success": False, "message": f"Training job '{training_id}' not found"}

        if job.get("status") == TrainingStatus.RUNNING.value:
            return {
                "success": False,
                "message": "Cannot cancel a running job. Wait for completion or restart the server.",
            }

        if job.get("status") in [TrainingStatus.COMPLETED.value, TrainingStatus.FAILED.value]:
            return {"success": False, "message": "Training job already finished"}

        self._update_job_status(training_id, TrainingStatus.CANCELLED)
        return {"success": True, "message": "Training job cancelled"}

    # ============== Inference Operations ==============

    async def predict(
        self,
        image_base64: str,
        model_name: str = "default",
        confidence: float = 0.25,
        iou: float = 0.45
    ) -> Dict:
        """Run inference on an image."""
        try:
            # Run in executor to not block
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: yolo_training_client.predict(
                    image_base64, model_name, confidence, iou
                )
            )
            return result
        except ValueError as e:
            return {
                "success": False,
                "detections": [],
                "model_used": model_name,
                "processing_time_ms": 0,
                "image_size": {},
                "error": str(e),
            }


# Global instance
yolo_training_handler = YoloTrainingHandler()
