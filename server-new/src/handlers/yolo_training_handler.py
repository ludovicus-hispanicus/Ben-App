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

from clients.yolo_training_client import yolo_training_client, DATASETS_PATH, MODELS_PATH, PDF_IMAGES_PATH
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

    def add_classes_to_dataset(self, dataset_name: str, new_classes: List[str]) -> Dict:
        """Add new classes to an existing dataset."""
        try:
            result = yolo_training_client.add_classes_to_dataset(dataset_name, new_classes)
            return {
                "success": True,
                **result,
            }
        except ValueError as e:
            return {
                "success": False,
                "message": str(e),
            }

    def delete_class_from_dataset(self, dataset_name: str, class_id: int) -> Dict:
        """Delete a class from a dataset."""
        try:
            result = yolo_training_client.delete_class_from_dataset(dataset_name, class_id)
            return {
                "success": True,
                **result,
            }
        except ValueError as e:
            return {
                "success": False,
                "message": str(e),
            }

    def update_class_color(self, dataset_name: str, class_id: int, color: str) -> Dict:
        """Update the color of a class in a dataset."""
        try:
            result = yolo_training_client.update_class_color(dataset_name, class_id, color)
            return {
                "success": True,
                **result,
                "message": f"Updated color for class {class_id}",
            }
        except ValueError as e:
            return {
                "success": False,
                "message": str(e),
            }

    def update_dataset_metadata(self, dataset_name: str, name: str = None, description: str = None, curated: bool = None) -> Dict:
        """Update dataset name, description, and/or curated flag."""
        try:
            result = yolo_training_client.update_dataset_metadata(dataset_name, name=name, description=description, curated=curated)
            return {
                "success": True,
                **result,
                "message": "Dataset metadata updated",
            }
        except ValueError as e:
            return {
                "success": False,
                "message": str(e),
            }

    def rename_class(self, dataset_name: str, class_id: int, new_name: str) -> Dict:
        """Rename a class in a dataset."""
        try:
            result = yolo_training_client.rename_class(dataset_name, class_id, new_name)
            return {
                "success": True,
                **result,
                "message": f"Renamed class '{result['old_name']}' to '{result['new_name']}'",
            }
        except ValueError as e:
            return {
                "success": False,
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

    def merge_datasets(self, source_names: List[str], target_name: str, description: str = None) -> Dict:
        """Merge multiple datasets into a new one."""
        try:
            if not source_names or len(source_names) < 2:
                return {"success": False, "message": "Need at least 2 source datasets to merge"}
            if not target_name or not target_name.strip():
                return {"success": False, "message": "Target dataset name is required"}
            return yolo_training_client.merge_datasets(source_names, target_name.strip(), description)
        except ValueError as e:
            return {"success": False, "message": str(e)}

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

    def toggle_image_curated(self, dataset_name: str, image_id: str, curated: bool) -> Dict:
        """Mark or unmark an image as curated."""
        try:
            result = yolo_training_client.toggle_image_curated(dataset_name, image_id, curated)
            return {"success": True, **result}
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

    # ============== Dataset Export ==============

    def export_dataset(self, dataset_name: str, format: str = "training") -> str:
        """
        Export a dataset as a zip file.

        Args:
            dataset_name: Name of the dataset
            format: "training" (YOLO format) or "snippets" (cropped images by page)

        Returns:
            Path to the temporary zip file (caller must delete after use).
        """
        dataset_path = DATASETS_PATH / dataset_name
        if not dataset_path.exists():
            raise ValueError(f"Dataset '{dataset_name}' not found")

        if format == "snippets":
            return yolo_training_client.export_dataset_snippets_zip(dataset_name)
        else:
            return yolo_training_client.export_dataset_zip(dataset_name)

    def save_snippets_to_library(self, dataset_name: str, project_id: str = None, project_name: str = None) -> Dict:
        """
        Save dataset snippets to the Pages library.

        Args:
            dataset_name: Name of the dataset
            project_id: Existing project to save into (optional)
            project_name: Name for new project (optional, defaults to {dataset_name}_snippets)
        """
        return yolo_training_client.save_snippets_to_library(dataset_name, project_id, project_name)

    def save_ahw_entries_to_library(self, dataset_name: str, project_id: str = None, project_name: str = None) -> Dict:
        """Save merged AHw dictionary entries to the Pages library."""
        return yolo_training_client.save_ahw_entries_to_library(dataset_name, project_id, project_name)

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

            # Progress callback: updates DB on each epoch so SSE stream picks it up
            def progress_callback(current_epoch, total_epochs, progress_pct, metrics, eta_seconds):
                update_kwargs = {
                    "current_epoch": current_epoch,
                    "total_epochs": total_epochs,
                    "progress_percent": progress_pct,
                }
                if metrics:
                    update_kwargs["metrics"] = metrics
                if eta_seconds is not None:
                    update_kwargs["eta_seconds"] = eta_seconds
                self._update_job_status(training_id, TrainingStatus.RUNNING, **update_kwargs)

            # Run training (this blocks)
            result = yolo_training_client.train_model(
                dataset_name=dataset_name,
                output_name=output_name,
                base_model=base_model,
                config=config,
                progress_callback=progress_callback,
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

    def get_training_logs(self, training_id: str) -> Dict:
        """Get training logs (results.csv) for a training job."""
        import csv
        from clients.yolo_training_client import TRAINING_RUNS_PATH

        # Find job to get output_name
        job = self._db[self.TRAINING_JOBS_COLLECTION].find_one({"_id": training_id})
        if training_id in self._active_jobs:
            job = self._active_jobs[training_id]

        if not job:
            return {"success": False, "message": "Training job not found", "epochs": []}

        output_name = job.get("output_name", "")
        results_path = TRAINING_RUNS_PATH / output_name / "results.csv"

        if not results_path.exists():
            return {"success": True, "epochs": [], "message": "No results yet"}

        epochs = []
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                content = f.read()
            reader = csv.DictReader(content.strip().splitlines())
            for row in reader:
                try:
                    # Strip whitespace from keys (YOLO adds spaces in CSV headers)
                    row = {k.strip(): v.strip() if v else "0" for k, v in row.items()}
                    epochs.append({
                        "epoch": int(float(row.get("epoch", 0))),
                        "box_loss": round(float(row.get("train/box_loss", 0)), 4),
                        "cls_loss": round(float(row.get("train/cls_loss", 0)), 4),
                        "dfl_loss": round(float(row.get("train/dfl_loss", 0)), 4),
                        "precision": round(float(row.get("metrics/precision(B)", 0)), 4),
                        "recall": round(float(row.get("metrics/recall(B)", 0)), 4),
                        "mAP50": round(float(row.get("metrics/mAP50(B)", 0)), 4),
                        "mAP50_95": round(float(row.get("metrics/mAP50-95(B)", 0)), 4),
                        "val_box_loss": round(float(row.get("val/box_loss", 0)), 4),
                        "val_cls_loss": round(float(row.get("val/cls_loss", 0)), 4),
                    })
                except (ValueError, TypeError):
                    # Skip partial/corrupt rows (e.g. mid-write during training)
                    continue
        except Exception as e:
            logger.error(f"Error reading results.csv: {e}")
            return {"success": False, "message": str(e), "epochs": []}

        return {"success": True, "epochs": epochs}

    def list_training_jobs(self, user_id: str = None, limit: int = 20) -> List[Dict]:
        """List recent training jobs."""
        query = {}
        if user_id:
            query["user_id"] = user_id

        # Use find_many with sort/limit params (compatible with local DB mock)
        jobs = self._db[self.TRAINING_JOBS_COLLECTION].find_many(
            query,
            limit=limit,
            sort=[("created_at", -1)]
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

    # ============== Model Activation ==============

    async def activate_model(self, model_name: str) -> Dict:
        """Set a trained model as the active/default model."""
        try:
            return yolo_training_client.activate_model(model_name)
        except ValueError as e:
            return {"success": False, "error": str(e)}

    async def get_active_model(self) -> Dict:
        """Get the currently active model."""
        return yolo_training_client.get_active_model()

    # ============== Auto-Annotate Operations ==============

    AUTO_ANNOTATE_JOBS_COLLECTION = "yolo_auto_annotate_jobs"

    async def start_auto_annotate(
        self,
        source_project_id: str,
        model_name: str,
        dataset_name: str,
        confidence: float = 0.25,
        iou: float = 0.45,
        val_ratio: float = 0.2,
        user_id: str = None,
    ) -> Dict:
        """Start an auto-annotation job asynchronously."""

        # Validate model exists
        try:
            yolo_training_client.get_model_path(model_name)
        except ValueError as e:
            return {"success": False, "job_id": None, "message": str(e)}

        # Validate project exists
        from handlers.pages_handler import PagesHandler
        pages_handler = PagesHandler()
        project = pages_handler.get_project(source_project_id)
        if project is None:
            return {"success": False, "job_id": None, "message": f"Project '{source_project_id}' not found"}

        # Check dataset name collision
        dataset_path = DATASETS_PATH / dataset_name
        if dataset_path.exists():
            return {"success": False, "job_id": None, "message": f"Dataset '{dataset_name}' already exists"}

        # Create job record
        job_id = str(uuid.uuid4())[:8]
        total_images = len(project.pages)
        job_record = {
            "_id": job_id,
            "job_id": job_id,
            "source_project_id": source_project_id,
            "source_project_name": project.name,
            "model_name": model_name,
            "dataset_name": dataset_name,
            "confidence": confidence,
            "iou": iou,
            "val_ratio": val_ratio,
            "status": "pending",
            "current_image": 0,
            "total_images": total_images,
            "total_detections": 0,
            "progress_percent": 0,
            "error": None,
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
        }

        self._db[self.AUTO_ANNOTATE_JOBS_COLLECTION].insert_one(job_record)
        self._active_jobs[job_id] = job_record

        # Start in background thread
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            self._executor,
            self._run_auto_annotate,
            job_id,
            source_project_id,
            model_name,
            dataset_name,
            confidence,
            iou,
            val_ratio,
        )

        logger.info(f"Started auto-annotate job {job_id}: {project.name} ({total_images} images) -> {dataset_name}")

        return {
            "success": True,
            "job_id": job_id,
            "total_images": total_images,
            "message": "Auto-annotation job started",
        }

    def _run_auto_annotate(
        self,
        job_id: str,
        source_project_id: str,
        model_name: str,
        dataset_name: str,
        confidence: float,
        iou: float,
        val_ratio: float,
    ):
        """Run auto-annotation in a background thread."""
        try:
            self._update_auto_annotate_status(job_id, "running", started_at=datetime.utcnow().isoformat())

            def progress_callback(current, total, message):
                progress_pct = round((current / total) * 100, 1)
                self._update_auto_annotate_status(
                    job_id,
                    "running",
                    current_image=current,
                    progress_percent=progress_pct,
                )

            result = yolo_training_client.auto_annotate_dataset(
                source_project_id=source_project_id,
                model_name=model_name,
                dataset_name=dataset_name,
                confidence=confidence,
                iou=iou,
                val_ratio=val_ratio,
                progress_callback=progress_callback,
            )

            self._update_auto_annotate_status(
                job_id,
                "completed",
                completed_at=datetime.utcnow().isoformat(),
                progress_percent=100,
                current_image=result["total_images"],
                total_detections=result["total_detections"],
            )

            logger.info(f"Auto-annotate job {job_id} completed: {result['total_detections']} detections across {result['total_images']} images")

        except Exception as e:
            logger.error(f"Auto-annotate job {job_id} failed: {e}")
            self._update_auto_annotate_status(
                job_id,
                "failed",
                error=str(e),
                completed_at=datetime.utcnow().isoformat(),
            )

        finally:
            if job_id in self._active_jobs:
                del self._active_jobs[job_id]

    def _update_auto_annotate_status(self, job_id: str, status: str, **kwargs):
        """Update an auto-annotate job's status."""
        update = {"status": status}
        update.update(kwargs)

        self._db[self.AUTO_ANNOTATE_JOBS_COLLECTION].update_one(
            {"_id": job_id},
            {"$set": update}
        )

        if job_id in self._active_jobs:
            self._active_jobs[job_id].update(update)

    def get_auto_annotate_status(self, job_id: str) -> Dict:
        """Get the current status of an auto-annotation job."""
        # Check active jobs first (more up-to-date)
        if job_id in self._active_jobs:
            job = self._active_jobs[job_id]
        else:
            job = self._db[self.AUTO_ANNOTATE_JOBS_COLLECTION].find_one({"_id": job_id})

        if not job:
            return {"success": False, "error": f"Job '{job_id}' not found"}

        return {
            "success": True,
            "job_id": job["job_id"],
            "status": job.get("status", "pending"),
            "source_project_name": job.get("source_project_name", ""),
            "model_name": job.get("model_name", ""),
            "dataset_name": job.get("dataset_name", ""),
            "current_image": job.get("current_image", 0),
            "total_images": job.get("total_images", 0),
            "total_detections": job.get("total_detections", 0),
            "progress_percent": job.get("progress_percent", 0),
            "error": job.get("error"),
            "created_at": job.get("created_at"),
            "completed_at": job.get("completed_at"),
        }


# Global instance
yolo_training_handler = YoloTrainingHandler()
