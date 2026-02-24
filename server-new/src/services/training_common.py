"""
Shared training types used by Nemotron, DeepSeek, and Kraken training services.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TrainingStatus(Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    TRAINING = "training"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TrainingProgress:
    status: TrainingStatus
    epoch: int
    total_epochs: int
    accuracy: float
    val_accuracy: float
    loss: float
    eta_seconds: int
    message: str
    model_name: str = None
    error: str = None
    started_at: str = None
    completed_at: str = None
    epoch_history: list = None
    best_accuracy: float = 0.0
    best_loss: float = float('inf')
    no_improve_count: int = 0
    early_stopped: bool = False

    def __post_init__(self):
        if self.epoch_history is None:
            self.epoch_history = []

    def to_dict(self):
        return {
            "status": self.status.value,
            "current_epoch": self.epoch,
            "total_epochs": self.total_epochs,
            "accuracy": self.accuracy,
            "val_accuracy": self.val_accuracy,
            "loss": self.loss,
            "eta_seconds": self.eta_seconds,
            "message": self.message,
            "model_name": self.model_name,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "epoch_history": self.epoch_history,
            "best_accuracy": self.best_accuracy,
            "no_improve_count": self.no_improve_count,
            "early_stopped": self.early_stopped,
        }
