# Kraken OCR Training Integration Plan

A comprehensive plan for adding user-trainable OCR capabilities to the BEn-app, allowing users to train custom Kraken models on their own annotated data.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Data Requirements](#data-requirements)
4. [Backend Implementation](#backend-implementation)
5. [Frontend Implementation](#frontend-implementation)
6. [Training Pipeline](#training-pipeline)
7. [Model Management](#model-management)
8. [Implementation Phases](#implementation-phases)
9. [API Specification](#api-specification)
10. [UI/UX Design](#uiux-design)

---

## Overview

### Goal
Enable users to train custom Kraken OCR models directly from the application interface, using their own corrected/annotated data.

### Key Features
- **Data validation**: Automatically check if minimum training data is available
- **One-click training**: Simple "Train Model" button when ready
- **Progress tracking**: Real-time training progress and metrics
- **Model versioning**: Save and manage multiple trained models
- **A/B comparison**: Test new model vs baseline on sample images

### User Flow
```
User corrects OCR errors → System accumulates corrections →
Minimum data threshold reached → Training button activates →
User clicks "Train" → Training runs in background →
User receives notification → New model available for use
```

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Angular)                       │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Training     │  │ Progress     │  │ Model Management     │   │
│  │ Dashboard    │  │ Monitor      │  │ (Select/Compare)     │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                           │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Training     │  │ Data         │  │ Model                │   │
│  │ Controller   │  │ Validator    │  │ Registry             │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Kraken Training Service                       │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Data         │  │ ketos train  │  │ Model                │   │
│  │ Preparation  │  │ (subprocess) │  │ Evaluation           │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Storage                                     │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Training     │  │ Trained      │  │ Training             │   │
│  │ Data (ALTO)  │  │ Models       │  │ Logs/Metrics         │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Docker Integration

The training service can be added to the existing `docker-compose.yml`:

```yaml
services:
  # ... existing services ...

  kraken-trainer:
    build:
      context: ./kraken-trainer
      dockerfile: Dockerfile
    volumes:
      - ./training-data:/app/training-data
      - ./models:/app/models
    environment:
      - CUDA_VISIBLE_DEVICES=0  # If GPU available
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

---

## Data Requirements

### Minimum Training Data

| Data Type | Minimum | Recommended | Purpose |
|-----------|---------|-------------|---------|
| **Line images** | 100 | 500+ | Individual text line images |
| **Ground truth** | 100 | 500+ | Corrected transcriptions |
| **Unique characters** | 50+ | 100+ | Character coverage |
| **Validation split** | 10% | 20% | Model evaluation |

### Data Sources in BEn-app

1. **User corrections**: When users correct OCR output in the CuReD component
2. **Validated texts**: Approved transliterations with bounding boxes
3. **Manual annotations**: Explicit training data creation

### Training Data Format

Kraken accepts several formats. We'll use **ALTO XML** (already used in the app):

```xml
<alto>
  <Layout>
    <Page>
      <PrintSpace>
        <TextLine BASELINE="100" HPOS="50" VPOS="80" WIDTH="400" HEIGHT="40">
          <String CONTENT="qa-ba-lu" />
        </TextLine>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
```

Or **plain text pairs**:
```
image_001.png → qa-ba-lu šá da-gan
image_002.png → i-na qá-ab-li-im
```

---

## Backend Implementation

### New Files Structure

```
server/src/
├── api/
│   └── routers/
│       └── training.py          # Training API endpoints
├── handlers/
│   └── training_handler.py      # Training business logic
├── services/
│   └── kraken_trainer.py        # Kraken training wrapper
├── models/
│   └── training_models.py       # Pydantic models
└── utils/
    └── training_data_validator.py  # Data validation
```

### Key Backend Components

#### 1. Training Data Validator (`training_data_validator.py`)

```python
from dataclasses import dataclass
from typing import List, Tuple
import os

@dataclass
class TrainingDataStatus:
    total_samples: int
    unique_characters: int
    estimated_quality: float  # 0-1
    is_ready: bool
    missing_requirements: List[str]

class TrainingDataValidator:
    MIN_SAMPLES = 100
    MIN_CHARACTERS = 50
    MIN_QUALITY = 0.7

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def validate(self) -> TrainingDataStatus:
        """Check if training data meets minimum requirements."""
        samples = self._count_samples()
        chars = self._count_unique_characters()
        quality = self._estimate_quality()

        missing = []
        if samples < self.MIN_SAMPLES:
            missing.append(f"Need {self.MIN_SAMPLES - samples} more samples")
        if chars < self.MIN_CHARACTERS:
            missing.append(f"Need {self.MIN_CHARACTERS - chars} more unique characters")
        if quality < self.MIN_QUALITY:
            missing.append(f"Quality score {quality:.2f} below threshold {self.MIN_QUALITY}")

        return TrainingDataStatus(
            total_samples=samples,
            unique_characters=chars,
            estimated_quality=quality,
            is_ready=len(missing) == 0,
            missing_requirements=missing
        )

    def _count_samples(self) -> int:
        """Count available training samples."""
        # Count line images with ground truth
        pass

    def _count_unique_characters(self) -> int:
        """Count unique characters in ground truth."""
        pass

    def _estimate_quality(self) -> float:
        """Estimate data quality based on consistency checks."""
        pass
```

#### 2. Kraken Trainer Service (`kraken_trainer.py`)

```python
import subprocess
import asyncio
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass
from enum import Enum

class TrainingStatus(Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    TRAINING = "training"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"

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

class KrakenTrainer:
    def __init__(
        self,
        training_data_dir: str,
        output_dir: str,
        base_model: Optional[str] = None,
        device: str = "cpu"
    ):
        self.training_data_dir = Path(training_data_dir)
        self.output_dir = Path(output_dir)
        self.base_model = base_model
        self.device = device
        self.process: Optional[subprocess.Popen] = None
        self.progress = TrainingProgress(
            status=TrainingStatus.IDLE,
            epoch=0, total_epochs=50,
            accuracy=0.0, val_accuracy=0.0, loss=0.0,
            eta_seconds=0, message=""
        )

    async def start_training(
        self,
        epochs: int = 50,
        batch_size: int = 4,
        learning_rate: float = 0.0001,
        progress_callback: Optional[Callable] = None
    ) -> str:
        """Start Kraken training process."""

        self.progress.status = TrainingStatus.PREPARING
        self.progress.total_epochs = epochs

        # Prepare training command
        model_name = f"custom_model_{int(time.time())}"
        output_path = self.output_dir / f"{model_name}.mlmodel"

        cmd = [
            "ketos", "train",
            "-d", self.device,
            "-f", "alto",  # or "binary" for preprocessed data
            "-o", str(output_path),
            "-N", str(epochs),
            "-B", str(batch_size),
            "-r", str(learning_rate),
            "--workers", "4",
        ]

        # Add base model for fine-tuning
        if self.base_model:
            cmd.extend(["-i", self.base_model])

        # Add training data
        cmd.append(str(self.training_data_dir / "*.xml"))

        # Start training process
        self.progress.status = TrainingStatus.TRAINING
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Monitor progress
        async for line in self.process.stdout:
            self._parse_progress(line.decode())
            if progress_callback:
                await progress_callback(self.progress)

        await self.process.wait()

        if self.process.returncode == 0:
            self.progress.status = TrainingStatus.COMPLETED
            return str(output_path)
        else:
            self.progress.status = TrainingStatus.FAILED
            stderr = await self.process.stderr.read()
            raise RuntimeError(f"Training failed: {stderr.decode()}")

    def _parse_progress(self, line: str):
        """Parse Kraken training output for progress info."""
        # Example: "epoch 10/50 - loss: 0.234 - accuracy: 0.891"
        import re
        epoch_match = re.search(r"epoch\s+(\d+)/(\d+)", line)
        if epoch_match:
            self.progress.epoch = int(epoch_match.group(1))
            self.progress.total_epochs = int(epoch_match.group(2))

        loss_match = re.search(r"loss:\s+([\d.]+)", line)
        if loss_match:
            self.progress.loss = float(loss_match.group(1))

        acc_match = re.search(r"accuracy:\s+([\d.]+)", line)
        if acc_match:
            self.progress.accuracy = float(acc_match.group(1))

    def cancel_training(self):
        """Cancel ongoing training."""
        if self.process:
            self.process.terminate()
            self.progress.status = TrainingStatus.IDLE
```

#### 3. Training Router (`training.py`)

```python
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import asyncio

router = APIRouter(prefix="/training", tags=["training"])

class TrainingConfig(BaseModel):
    epochs: int = 50
    batch_size: int = 4
    learning_rate: float = 0.0001
    base_model: Optional[str] = None
    model_name: Optional[str] = None

class TrainingStatusResponse(BaseModel):
    is_ready: bool
    total_samples: int
    unique_characters: int
    missing_requirements: List[str]
    current_training: Optional[dict] = None

@router.get("/status")
async def get_training_status() -> TrainingStatusResponse:
    """Check if training data requirements are met."""
    validator = TrainingDataValidator(TRAINING_DATA_DIR)
    status = validator.validate()

    # Check for ongoing training
    current = None
    if trainer.progress.status != TrainingStatus.IDLE:
        current = {
            "status": trainer.progress.status.value,
            "epoch": trainer.progress.epoch,
            "total_epochs": trainer.progress.total_epochs,
            "accuracy": trainer.progress.accuracy
        }

    return TrainingStatusResponse(
        is_ready=status.is_ready,
        total_samples=status.total_samples,
        unique_characters=status.unique_characters,
        missing_requirements=status.missing_requirements,
        current_training=current
    )

@router.post("/start")
async def start_training(
    config: TrainingConfig,
    background_tasks: BackgroundTasks
):
    """Start model training."""
    # Validate data first
    validator = TrainingDataValidator(TRAINING_DATA_DIR)
    status = validator.validate()

    if not status.is_ready:
        raise HTTPException(400, f"Training data not ready: {status.missing_requirements}")

    # Check if already training
    if trainer.progress.status == TrainingStatus.TRAINING:
        raise HTTPException(409, "Training already in progress")

    # Start training in background
    background_tasks.add_task(
        trainer.start_training,
        epochs=config.epochs,
        batch_size=config.batch_size,
        learning_rate=config.learning_rate
    )

    return {"message": "Training started", "model_name": config.model_name}

@router.get("/progress")
async def get_training_progress():
    """Get current training progress (SSE stream)."""
    async def progress_stream():
        while trainer.progress.status in [TrainingStatus.PREPARING, TrainingStatus.TRAINING]:
            yield f"data: {trainer.progress.json()}\n\n"
            await asyncio.sleep(1)
        yield f"data: {trainer.progress.json()}\n\n"

    return StreamingResponse(
        progress_stream(),
        media_type="text/event-stream"
    )

@router.post("/cancel")
async def cancel_training():
    """Cancel ongoing training."""
    trainer.cancel_training()
    return {"message": "Training cancelled"}

@router.get("/models")
async def list_models():
    """List available trained models."""
    models_dir = Path(MODELS_DIR)
    models = []
    for model_path in models_dir.glob("*.mlmodel"):
        stat = model_path.stat()
        models.append({
            "name": model_path.stem,
            "path": str(model_path),
            "size_mb": stat.st_size / 1024 / 1024,
            "created": stat.st_ctime
        })
    return {"models": sorted(models, key=lambda x: x["created"], reverse=True)}

@router.post("/models/{model_name}/activate")
async def activate_model(model_name: str):
    """Set a model as the active OCR model."""
    model_path = Path(MODELS_DIR) / f"{model_name}.mlmodel"
    if not model_path.exists():
        raise HTTPException(404, f"Model not found: {model_name}")

    # Update active model configuration
    # This would update the CuReD handler to use the new model
    pass

    return {"message": f"Model {model_name} activated"}
```

---

## Frontend Implementation

### New Angular Components

```
app/src/app/components/
├── training/
│   ├── training.module.ts
│   ├── training-dashboard/
│   │   ├── training-dashboard.component.ts
│   │   ├── training-dashboard.component.html
│   │   └── training-dashboard.component.scss
│   ├── training-progress/
│   │   ├── training-progress.component.ts
│   │   └── training-progress.component.html
│   └── model-selector/
│       ├── model-selector.component.ts
│       └── model-selector.component.html
└── services/
    └── training.service.ts
```

### Training Service (`training.service.ts`)

```typescript
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, Subject } from 'rxjs';
import { environment } from '../../environments/environment';

export interface TrainingStatus {
  is_ready: boolean;
  total_samples: number;
  unique_characters: number;
  missing_requirements: string[];
  current_training?: {
    status: string;
    epoch: number;
    total_epochs: number;
    accuracy: number;
  };
}

export interface TrainingConfig {
  epochs: number;
  batch_size: number;
  learning_rate: number;
  base_model?: string;
  model_name?: string;
}

export interface TrainingProgress {
  status: string;
  epoch: number;
  total_epochs: number;
  accuracy: number;
  val_accuracy: number;
  loss: number;
  eta_seconds: number;
  message: string;
}

export interface TrainedModel {
  name: string;
  path: string;
  size_mb: number;
  created: number;
}

@Injectable({
  providedIn: 'root'
})
export class TrainingService {
  private baseUrl = `${environment.apiUrl}/training`;
  private progressSubject = new Subject<TrainingProgress>();
  private eventSource?: EventSource;

  constructor(private http: HttpClient) {}

  getStatus(): Observable<TrainingStatus> {
    return this.http.get<TrainingStatus>(`${this.baseUrl}/status`);
  }

  startTraining(config: TrainingConfig): Observable<any> {
    return this.http.post(`${this.baseUrl}/start`, config);
  }

  cancelTraining(): Observable<any> {
    return this.http.post(`${this.baseUrl}/cancel`, {});
  }

  getModels(): Observable<{ models: TrainedModel[] }> {
    return this.http.get<{ models: TrainedModel[] }>(`${this.baseUrl}/models`);
  }

  activateModel(modelName: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/models/${modelName}/activate`, {});
  }

  // Server-Sent Events for real-time progress
  subscribeToProgress(): Observable<TrainingProgress> {
    this.eventSource = new EventSource(`${this.baseUrl}/progress`);

    this.eventSource.onmessage = (event) => {
      const progress = JSON.parse(event.data);
      this.progressSubject.next(progress);

      if (progress.status === 'completed' || progress.status === 'failed') {
        this.eventSource?.close();
      }
    };

    this.eventSource.onerror = () => {
      this.eventSource?.close();
    };

    return this.progressSubject.asObservable();
  }

  unsubscribeFromProgress(): void {
    this.eventSource?.close();
  }
}
```

### Training Dashboard Component (`training-dashboard.component.html`)

```html
<div class="training-dashboard">
  <h2>OCR Model Training</h2>

  <!-- Status Card -->
  <mat-card class="status-card">
    <mat-card-header>
      <mat-card-title>Training Data Status</mat-card-title>
    </mat-card-header>
    <mat-card-content>
      <div class="stats-grid">
        <div class="stat">
          <span class="value">{{ status?.total_samples || 0 }}</span>
          <span class="label">Samples</span>
          <mat-progress-bar
            mode="determinate"
            [value]="(status?.total_samples || 0) / 100 * 100">
          </mat-progress-bar>
          <span class="target">Target: 100+</span>
        </div>

        <div class="stat">
          <span class="value">{{ status?.unique_characters || 0 }}</span>
          <span class="label">Unique Characters</span>
          <mat-progress-bar
            mode="determinate"
            [value]="(status?.unique_characters || 0) / 50 * 100">
          </mat-progress-bar>
          <span class="target">Target: 50+</span>
        </div>
      </div>

      <!-- Missing Requirements -->
      <div *ngIf="status?.missing_requirements?.length" class="requirements">
        <mat-icon color="warn">warning</mat-icon>
        <ul>
          <li *ngFor="let req of status.missing_requirements">{{ req }}</li>
        </ul>
      </div>

      <!-- Ready Status -->
      <div *ngIf="status?.is_ready" class="ready-status">
        <mat-icon color="primary">check_circle</mat-icon>
        <span>Ready to train!</span>
      </div>
    </mat-card-content>
  </mat-card>

  <!-- Training Configuration -->
  <mat-card class="config-card" *ngIf="status?.is_ready && !isTraining">
    <mat-card-header>
      <mat-card-title>Training Configuration</mat-card-title>
    </mat-card-header>
    <mat-card-content>
      <form [formGroup]="configForm">
        <mat-form-field>
          <mat-label>Model Name</mat-label>
          <input matInput formControlName="model_name" placeholder="my_custom_model">
        </mat-form-field>

        <mat-form-field>
          <mat-label>Epochs</mat-label>
          <input matInput type="number" formControlName="epochs">
          <mat-hint>More epochs = longer training, potentially better accuracy</mat-hint>
        </mat-form-field>

        <mat-form-field>
          <mat-label>Base Model (Fine-tuning)</mat-label>
          <mat-select formControlName="base_model">
            <mat-option [value]="null">Train from scratch</mat-option>
            <mat-option *ngFor="let model of availableModels" [value]="model.path">
              {{ model.name }}
            </mat-option>
          </mat-select>
          <mat-hint>Fine-tuning an existing model is faster and often better</mat-hint>
        </mat-form-field>

        <mat-expansion-panel>
          <mat-expansion-panel-header>
            Advanced Settings
          </mat-expansion-panel-header>
          <mat-form-field>
            <mat-label>Batch Size</mat-label>
            <input matInput type="number" formControlName="batch_size">
          </mat-form-field>
          <mat-form-field>
            <mat-label>Learning Rate</mat-label>
            <input matInput type="number" formControlName="learning_rate" step="0.0001">
          </mat-form-field>
        </mat-expansion-panel>
      </form>
    </mat-card-content>
    <mat-card-actions>
      <button mat-raised-button color="primary"
              (click)="startTraining()"
              [disabled]="!status?.is_ready">
        <mat-icon>model_training</mat-icon>
        Start Training
      </button>
    </mat-card-actions>
  </mat-card>

  <!-- Training Progress -->
  <mat-card class="progress-card" *ngIf="isTraining">
    <mat-card-header>
      <mat-card-title>Training in Progress</mat-card-title>
    </mat-card-header>
    <mat-card-content>
      <div class="progress-info">
        <div class="epoch">
          Epoch {{ progress?.epoch || 0 }} / {{ progress?.total_epochs || 50 }}
        </div>
        <mat-progress-bar
          mode="determinate"
          [value]="(progress?.epoch || 0) / (progress?.total_epochs || 50) * 100">
        </mat-progress-bar>

        <div class="metrics">
          <div class="metric">
            <span class="label">Accuracy</span>
            <span class="value">{{ (progress?.accuracy || 0) * 100 | number:'1.1-1' }}%</span>
          </div>
          <div class="metric">
            <span class="label">Loss</span>
            <span class="value">{{ progress?.loss || 0 | number:'1.4-4' }}</span>
          </div>
          <div class="metric">
            <span class="label">ETA</span>
            <span class="value">{{ formatEta(progress?.eta_seconds) }}</span>
          </div>
        </div>
      </div>
    </mat-card-content>
    <mat-card-actions>
      <button mat-button color="warn" (click)="cancelTraining()">
        <mat-icon>cancel</mat-icon>
        Cancel Training
      </button>
    </mat-card-actions>
  </mat-card>

  <!-- Model Selector -->
  <mat-card class="models-card">
    <mat-card-header>
      <mat-card-title>Available Models</mat-card-title>
    </mat-card-header>
    <mat-card-content>
      <mat-list>
        <mat-list-item *ngFor="let model of availableModels">
          <mat-icon matListItemIcon>smart_toy</mat-icon>
          <div matListItemTitle>{{ model.name }}</div>
          <div matListItemLine>
            {{ model.size_mb | number:'1.1-1' }} MB ·
            Created {{ model.created | date:'short' }}
          </div>
          <button mat-icon-button matListItemMeta (click)="activateModel(model)">
            <mat-icon>check_circle</mat-icon>
          </button>
        </mat-list-item>
      </mat-list>
    </mat-card-content>
  </mat-card>
</div>
```

---

## Training Pipeline

### Data Collection Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Data Collection Sources                       │
└─────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ CuReD Component │  │ Text Editor     │  │ Manual Upload   │
│ (OCR Correction)│  │ (Validation)    │  │ (ALTO/PageXML)  │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Training Data Store                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Line Images │  │ Ground Truth│  │ Metadata (source, date) │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Training Workflow

1. **Data Export**: Convert corrections to Kraken training format
2. **Data Split**: 80% training, 20% validation
3. **Preprocessing**: Normalize images, validate ground truth
4. **Training**: Run `ketos train` with configuration
5. **Evaluation**: Test on held-out validation set
6. **Model Save**: Store with metadata and metrics

### Integration with Existing CuReD Handler

Modify `server/src/handlers/cured_handler.py` to save corrections:

```python
class CuredHandler:
    # ... existing code ...

    async def save_correction(
        self,
        image_id: str,
        line_index: int,
        original_text: str,
        corrected_text: str,
        line_image: bytes
    ):
        """Save a user correction as training data."""
        training_dir = Path(TRAINING_DATA_DIR)
        training_dir.mkdir(exist_ok=True)

        # Save line image
        timestamp = int(time.time() * 1000)
        image_path = training_dir / f"{image_id}_{line_index}_{timestamp}.png"
        with open(image_path, "wb") as f:
            f.write(line_image)

        # Save ground truth
        gt_path = image_path.with_suffix(".gt.txt")
        with open(gt_path, "w", encoding="utf-8") as f:
            f.write(corrected_text)

        # Log for tracking
        log_path = training_dir / "corrections.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": timestamp,
                "image": str(image_path),
                "original": original_text,
                "corrected": corrected_text
            }) + "\n")
```

---

## Model Management

### Model Registry

```python
@dataclass
class ModelMetadata:
    name: str
    version: str
    created_at: datetime
    training_samples: int
    accuracy: float
    character_set: List[str]
    base_model: Optional[str]
    is_active: bool

class ModelRegistry:
    def __init__(self, models_dir: str):
        self.models_dir = Path(models_dir)
        self.metadata_file = self.models_dir / "registry.json"

    def register(self, model_path: str, metadata: ModelMetadata):
        """Register a newly trained model."""
        pass

    def get_active(self) -> Optional[str]:
        """Get the currently active model path."""
        pass

    def set_active(self, model_name: str):
        """Set a model as active."""
        pass

    def list_models(self) -> List[ModelMetadata]:
        """List all available models."""
        pass

    def delete(self, model_name: str):
        """Delete a model."""
        pass
```

---

## Implementation Phases

### Phase 1: Backend Foundation (1-2 weeks)
- [ ] Create training data storage structure
- [ ] Implement data validator
- [ ] Create Kraken trainer service wrapper
- [ ] Add training API endpoints
- [ ] Modify CuReD handler to save corrections

### Phase 2: Frontend Dashboard (1-2 weeks)
- [ ] Create training service
- [ ] Build training dashboard component
- [ ] Add progress monitoring (SSE)
- [ ] Create model selector component
- [ ] Integrate into admin panel

### Phase 3: Integration & Testing (1 week)
- [ ] Connect frontend to backend
- [ ] End-to-end testing
- [ ] Performance optimization
- [ ] Error handling improvements

### Phase 4: Enhancement (Optional)
- [ ] A/B model comparison tool
- [ ] Automatic retraining scheduler
- [ ] Training data augmentation
- [ ] Multi-GPU support

---

## API Specification

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/training/status` | Get training data status and requirements |
| POST | `/training/start` | Start model training |
| GET | `/training/progress` | SSE stream of training progress |
| POST | `/training/cancel` | Cancel ongoing training |
| GET | `/training/models` | List trained models |
| POST | `/training/models/{name}/activate` | Set model as active |
| DELETE | `/training/models/{name}` | Delete a model |
| GET | `/training/data/export` | Export training data as ZIP |
| POST | `/training/data/import` | Import training data |

---

## UI/UX Design

### Training Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Training Dashboard                                    [Refresh] │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────┐  ┌─────────────────────────┐   │
│  │  Training Data Status       │  │  Quick Stats            │   │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━  │  │                         │   │
│  │  Samples: 127/100 ✓        │  │  📊 127 corrections     │   │
│  │  Characters: 89/50 ✓       │  │  🔤 89 unique chars     │   │
│  │  Quality: 0.85 ✓           │  │  📈 85% consistency     │   │
│  │                             │  │                         │   │
│  │  [🟢 Ready to Train]       │  │  Last trained: 3d ago   │   │
│  └─────────────────────────────┘  └─────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Training Configuration                                   │   │
│  │  ────────────────────────────────────────────────────────│   │
│  │  Model Name: [my_ahw_model_v2        ]                   │   │
│  │  Base Model: [▼ ahw_model_v1 (fine-tune)]               │   │
│  │  Epochs:     [50    ]  Batch Size: [4]                   │   │
│  │                                                           │   │
│  │  [▶ Advanced Settings]                                   │   │
│  │                                                           │   │
│  │              [ 🚀 Start Training ]                       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Available Models                                         │   │
│  │  ────────────────────────────────────────────────────────│   │
│  │  ● ahw_model_v1      16.2 MB   Jan 15, 2026   [Active]   │   │
│  │  ○ baseline_latin    12.8 MB   Jan 10, 2026   [Activate] │   │
│  │  ○ test_model        14.1 MB   Jan 8, 2026    [Activate] │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Training Progress Modal

```
┌─────────────────────────────────────────────────────────────────┐
│  Training in Progress                                    [X]     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│                    ⏳ Training Model                             │
│                    my_ahw_model_v2                               │
│                                                                  │
│     Epoch 23 / 50                                               │
│     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━░░░░░░░░░░░░░░░  46%       │
│                                                                  │
│     ┌─────────────┬─────────────┬─────────────┐                 │
│     │  Accuracy   │    Loss     │     ETA     │                 │
│     │   89.2%     │   0.0234    │   12 min    │                 │
│     └─────────────┴─────────────┴─────────────┘                 │
│                                                                  │
│     📈 Training Curve                                           │
│     ┌────────────────────────────────────────┐                  │
│     │    ╱╲    ╱─────────────────            │                  │
│     │   ╱  ╲  ╱                              │                  │
│     │  ╱    ╲╱                               │                  │
│     │ ╱                                      │                  │
│     └────────────────────────────────────────┘                  │
│                                                                  │
│                    [ Cancel Training ]                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Summary

This plan outlines a complete system for user-trainable OCR models:

1. **Automatic data collection** from user corrections
2. **Validation system** ensuring minimum data quality
3. **One-click training** with sensible defaults
4. **Real-time progress** via Server-Sent Events
5. **Model management** for versioning and comparison

The implementation leverages your existing Docker/WSL setup and integrates cleanly with the current CuReD workflow.

**Estimated Timeline**: 4-6 weeks for full implementation

---

*Document created: January 2026*
*Project: BEn-app Kraken Training Integration*
