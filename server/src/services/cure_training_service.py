"""
CuRe Training Service — Full training pipeline for ResNet18 sign classifier.

Adapted from CuneiformOcr/src/train.py (train_resnet18_classifier, train_end_eval).
Follows the same patterns as KrakenTrainingService and NemotronTrainingService.
"""
import datetime
import json
import logging
import os
import shutil
import time
from typing import Optional, Callable

import torch
import torch.nn as nn
import torch.optim as optim
import torchvision

from services.training_common import TrainingStatus, TrainingProgress


class CuReTrainingService:
    """Training service for CuRe ResNet18 sign classifier."""

    MIN_SIGNS = 500
    MIN_EPOCHS = 5
    PATIENCE = 5
    BATCH_SIZE = 256
    LEARNING_RATE = 0.001
    IMAGE_SIZE = 64

    def __init__(self):
        storage_path = os.environ.get("STORAGE_PATH", "data")
        self.training_dir = os.path.join(storage_path, "cure-training")
        self.crops_dir = os.path.join(self.training_dir, "crops")
        self.models_dir = os.path.join(storage_path, "cure_models")
        self.history_file = os.path.join(storage_path, "cure_training_history.json")

        self.progress = TrainingProgress(
            status=TrainingStatus.IDLE,
            epoch=0,
            total_epochs=0,
            accuracy=0.0,
            val_accuracy=0.0,
            loss=0.0,
            eta_seconds=0,
            message="Idle",
        )
        self._cancel_requested = False

    async def start_training(
        self,
        epochs: int = 50,
        model_name: Optional[str] = None,
        batch_size: int = BATCH_SIZE,
        learning_rate: float = LEARNING_RATE,
        base_model: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """
        Run the full CuRe training pipeline.

        Args:
            epochs: Number of training epochs
            model_name: Name for the output model
            batch_size: Training batch size
            learning_rate: Adam optimizer learning rate
            base_model: Optional existing model to fine-tune from
            progress_callback: Optional async callback for progress updates
        """
        self._cancel_requested = False
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        if not model_name:
            model_name = f"cure_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self.progress = TrainingProgress(
            status=TrainingStatus.PREPARING,
            epoch=0,
            total_epochs=epochs,
            accuracy=0.0,
            val_accuracy=0.0,
            loss=0.0,
            eta_seconds=0,
            message="Preparing training data...",
            model_name=model_name,
            started_at=datetime.datetime.now().isoformat(),
        )

        try:
            # ── Step 1: Build label mapping from crops directory ──
            from services.cure_label_service import CuReLabelService
            label_service = CuReLabelService()

            if not os.path.exists(self.crops_dir):
                raise ValueError(f"No training crops found at {self.crops_dir}")

            # Discover labels from directory names
            labels = sorted([
                d for d in os.listdir(self.crops_dir)
                if os.path.isdir(os.path.join(self.crops_dir, d))
            ])
            if not labels:
                raise ValueError("No label directories found in crops directory")

            label_service.load_from_label_list(labels)
            num_classes = label_service.num_classes
            logging.info(f"CuRe training: {num_classes} classes discovered")

            # ── Step 2: Create data loaders ──
            self.progress.message = "Creating data loaders..."
            if progress_callback:
                await progress_callback(self.progress)

            from services.cure_dataset import create_data_loaders
            train_loader, val_loader, test_loader, label_list = create_data_loaders(
                self.crops_dir, label_service.label_to_index, batch_size=batch_size
            )

            # ── Step 3: Build model ──
            self.progress.message = "Building model..."
            if progress_callback:
                await progress_callback(self.progress)

            model = torchvision.models.resnet18(weights="IMAGENET1K_V1")
            num_ftrs = model.fc.in_features
            model.fc = nn.Linear(num_ftrs, num_classes)
            model = model.double()  # float64 to match original CuneiformOcr
            model.to(device)

            # Optionally load base model weights
            if base_model:
                base_path = os.path.join(self.models_dir, f"{base_model}.pt")
                if os.path.exists(base_path):
                    state_dict = torch.load(base_path, map_location=device, weights_only=True)
                    model.load_state_dict(state_dict)
                    logging.info(f"CuRe training: loaded base model from {base_model}")

            criterion = nn.CrossEntropyLoss()
            optimizer = optim.Adam(model.parameters(), lr=learning_rate)

            # ── Step 4: Training loop ──
            self.progress.status = TrainingStatus.TRAINING
            self.progress.message = "Training..."
            best_val_acc = 0.0
            no_improve_count = 0
            epoch_times = []

            for epoch in range(epochs):
                if self._cancel_requested:
                    self.progress.status = TrainingStatus.CANCELLED
                    self.progress.message = "Training cancelled by user"
                    return self._make_result(model_name, False)

                epoch_start = time.time()

                # Train
                model.train()
                train_loss = 0.0
                train_correct = 0
                train_total = 0

                for inputs, labels_batch in train_loader:
                    inputs = inputs.to(device)
                    labels_batch = labels_batch.to(device)

                    outputs = model(inputs)
                    loss = criterion(outputs, labels_batch)

                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()

                    train_loss += loss.item()
                    _, predicted = torch.max(outputs.data, 1)
                    train_total += labels_batch.size(0)
                    train_correct += (predicted == labels_batch).sum().item()

                avg_train_loss = train_loss / max(1, len(train_loader))
                train_acc = 100.0 * train_correct / max(1, train_total)

                # Validate
                model.eval()
                val_loss = 0.0
                val_correct = 0
                val_total = 0

                with torch.no_grad():
                    for inputs, labels_batch in val_loader:
                        inputs = inputs.to(device)
                        labels_batch = labels_batch.to(device)

                        outputs = model(inputs)
                        loss = criterion(outputs, labels_batch)

                        val_loss += loss.item()
                        _, predicted = torch.max(outputs.data, 1)
                        val_total += labels_batch.size(0)
                        val_correct += (predicted == labels_batch).sum().item()

                avg_val_loss = val_loss / max(1, len(val_loader))
                val_acc = 100.0 * val_correct / max(1, val_total)

                epoch_time = time.time() - epoch_start
                epoch_times.append(epoch_time)

                # ETA calculation
                avg_epoch_time = sum(epoch_times) / len(epoch_times)
                remaining_epochs = epochs - (epoch + 1)
                eta_seconds = int(avg_epoch_time * remaining_epochs)

                # Early stopping check
                if val_acc > best_val_acc:
                    best_val_acc = val_acc
                    no_improve_count = 0
                else:
                    no_improve_count += 1

                # Update progress
                self.progress.epoch = epoch + 1
                self.progress.accuracy = round(train_acc, 2)
                self.progress.val_accuracy = round(val_acc, 2)
                self.progress.loss = round(avg_train_loss, 4)
                self.progress.eta_seconds = eta_seconds
                self.progress.best_accuracy = round(best_val_acc, 2)
                self.progress.no_improve_count = no_improve_count
                self.progress.message = (
                    f"Epoch {epoch + 1}/{epochs} — "
                    f"train_acc={train_acc:.1f}%, val_acc={val_acc:.1f}%, "
                    f"loss={avg_train_loss:.4f}"
                )
                self.progress.epoch_history.append({
                    "epoch": epoch + 1,
                    "train_loss": round(avg_train_loss, 4),
                    "train_accuracy": round(train_acc, 2),
                    "val_loss": round(avg_val_loss, 4),
                    "val_accuracy": round(val_acc, 2),
                    "epoch_time": round(epoch_time, 1),
                })

                logging.info(self.progress.message)

                if progress_callback:
                    await progress_callback(self.progress)

                # Early stopping
                if epoch >= self.MIN_EPOCHS and no_improve_count >= self.PATIENCE:
                    self.progress.early_stopped = True
                    logging.info(
                        f"CuRe training: early stopping at epoch {epoch + 1} "
                        f"(no improvement for {self.PATIENCE} epochs)"
                    )
                    break

            # ── Step 5: Test evaluation ──
            self.progress.status = TrainingStatus.EVALUATING
            self.progress.message = "Evaluating on test set..."

            model.eval()
            test_correct = 0
            test_total = 0

            with torch.no_grad():
                for inputs, labels_batch in test_loader:
                    inputs = inputs.to(device)
                    labels_batch = labels_batch.to(device)
                    outputs = model(inputs)
                    _, predicted = torch.max(outputs.data, 1)
                    test_total += labels_batch.size(0)
                    test_correct += (predicted == labels_batch).sum().item()

            test_acc = 100.0 * test_correct / max(1, test_total)
            logging.info(f"CuRe training: test accuracy = {test_acc:.2f}%")

            # ── Step 6: Save model ──
            os.makedirs(self.models_dir, exist_ok=True)
            model_path = os.path.join(self.models_dir, f"{model_name}.pt")
            torch.save(model.state_dict(), model_path)

            # Save label mapping
            mapping_path = os.path.join(self.models_dir, f"{model_name}_label_mapping.json")
            label_service.save_mapping(mapping_path)

            # Register model
            self._register_model(model_name, num_classes, test_acc, self.progress.epoch)

            # Auto-activate if no active model exists
            active_path = os.path.join(self.models_dir, "active_model.pt")
            if not os.path.exists(active_path):
                shutil.copy2(model_path, active_path)
                shutil.copy2(mapping_path, os.path.join(self.models_dir, "active_label_mapping.json"))
                with open(os.path.join(self.models_dir, "active_model_name.txt"), "w") as f:
                    f.write(model_name)
                logging.info(f"CuRe training: auto-activated model {model_name}")

            # Save training history
            self._save_history(model_name, test_acc, self.progress)

            # Done
            self.progress.status = TrainingStatus.COMPLETED
            self.progress.accuracy = round(test_acc, 2)
            self.progress.completed_at = datetime.datetime.now().isoformat()
            self.progress.message = (
                f"Training complete! Test accuracy: {test_acc:.2f}% "
                f"({self.progress.epoch} epochs, {num_classes} classes)"
            )

            logging.info(f"CuRe training complete: {model_name}, accuracy={test_acc:.2f}%")
            return self._make_result(model_name, True)

        except Exception as e:
            self.progress.status = TrainingStatus.FAILED
            self.progress.error = str(e)
            self.progress.message = f"Training failed: {e}"
            logging.error(f"CuRe training failed: {e}", exc_info=True)
            return self._make_result(model_name, False)

    def cancel_training(self):
        """Request training cancellation."""
        self._cancel_requested = True
        self.progress.message = "Cancellation requested..."
        logging.info("CuRe training: cancellation requested")

    def get_training_stats(self) -> dict:
        """Get training data statistics."""
        from handlers.cure_handler import cure_handler
        return cure_handler.get_annotation_stats()

    def get_models(self) -> list:
        """List all trained models from registry."""
        registry_path = os.path.join(self.models_dir, "registry.json")
        if not os.path.exists(registry_path):
            return []
        with open(registry_path, "r") as f:
            return json.load(f)

    def _register_model(self, model_name: str, num_classes: int, accuracy: float, epochs: int):
        """Add model to registry."""
        from handlers.cure_handler import cure_handler
        cure_handler._register_model(model_name, num_classes, accuracy, epochs)

    def _save_history(self, model_name: str, test_accuracy: float, progress: TrainingProgress):
        """Append training run to history file."""
        history = []
        if os.path.exists(self.history_file):
            with open(self.history_file, "r") as f:
                history = json.load(f)

        history.append({
            "model_name": model_name,
            "test_accuracy": round(test_accuracy, 2),
            "epochs_trained": progress.epoch,
            "early_stopped": progress.early_stopped,
            "best_val_accuracy": progress.best_accuracy,
            "started_at": progress.started_at,
            "completed_at": progress.completed_at,
            "epoch_history": progress.epoch_history,
        })

        with open(self.history_file, "w") as f:
            json.dump(history, f, indent=2)

    def _make_result(self, model_name: str, success: bool) -> dict:
        """Create a training result dict."""
        return {
            "success": success,
            "model_name": model_name,
            "status": self.progress.status.value,
            "accuracy": self.progress.accuracy,
            "val_accuracy": self.progress.val_accuracy,
            "epochs_trained": self.progress.epoch,
            "message": self.progress.message,
        }


# Global service instance
cure_training_service = CuReTrainingService()
