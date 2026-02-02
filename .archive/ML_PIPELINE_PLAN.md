# ML Pipeline Plan: CuReD + VLM Systems

A comprehensive plan for implementing two machine learning systems for document digitization in the BEn-app.

## Overview

### Two Systems

| System | Components | Purpose |
|--------|------------|---------|
| **CuReD** | YOLO + Kraken | Layout detection → OCR pipeline (general + dictionary-specific) |
| **VLM** (TBD name) | Vision-Language Model | Single model for layout + OCR (future) |

### Implementation Roadmap

```
Phase 1: YOLO Frontend Training
    ├── AHw dictionary model
    └── CAD dictionary model
            ↓
Phase 2: YOLO + Kraken Integration (CuReD)
    └── Auto-detect → OCR pipeline for all documents
            ↓
Phase 3: CuReD Dict (Specialized Models)
    ├── Tuned YOLO + Kraken for AHw
    └── Tuned YOLO + Kraken for CAD
            ↓
Phase 4: Trainable VLM (New System)
    └── Single model, external GPU training
```

---

## Phase 1: YOLO Frontend Training

### Goal
Enable users to train custom YOLO layout detection models from the browser.

### 1.1 Backend: Training Service

**New files:**
- `server/src/api/routers/yolo.py` - API endpoints
- `server/src/handlers/yolo_training_handler.py` - Training logic
- `server/src/clients/yolo_client.py` - YOLO model wrapper

**API Endpoints:**

```python
# POST /api/yolo/train
# Start training job
{
    "dataset_name": "ahw_layout",
    "epochs": 100,
    "batch_size": 4,
    "image_size": 1024,
    "base_model": "yolov8s.pt"
}

# GET /api/yolo/train/{job_id}/status
# SSE stream for training progress
# Returns: epoch, loss, mAP, ETA

# GET /api/yolo/models
# List available models
[
    {"name": "ahw_layout_v1", "created": "2026-01-28", "mAP": 0.989},
    {"name": "cad_layout_v1", "created": "2026-02-15", "mAP": 0.975}
]

# POST /api/yolo/predict
# Run inference on image
{
    "image": "<base64>",
    "model": "ahw_layout_v1",
    "confidence": 0.25
}
# Returns: list of {class_name, bbox, confidence}
```

### 1.2 Backend: Dataset Management

**Directory structure:**
```
server/data/yolo/
├── datasets/
│   ├── ahw_layout/
│   │   ├── dataset.yaml
│   │   ├── images/train/
│   │   ├── images/val/
│   │   ├── labels/train/
│   │   └── labels/val/
│   └── cad_layout/
│       └── ...
├── models/
│   ├── ahw_layout_v1/
│   │   ├── best.pt
│   │   └── metadata.json
│   └── cad_layout_v1/
│       └── ...
└── base_models/
    └── yolov8s.pt
```

**API Endpoints:**

```python
# POST /api/yolo/datasets
# Create new dataset
{
    "name": "ahw_layout",
    "classes": ["entry", "subentry", "guidewords", "page_number", "root_index"]
}

# POST /api/yolo/datasets/{name}/images
# Upload training image + annotations
{
    "image": "<base64>",
    "annotations": [
        {"class_id": 0, "x_center": 0.5, "y_center": 0.5, "width": 0.3, "height": 0.2}
    ]
}

# GET /api/yolo/datasets/{name}/stats
# Get dataset statistics
{
    "total_images": 45,
    "train_images": 40,
    "val_images": 5,
    "class_distribution": {"entry": 320, "subentry": 45, ...},
    "ready_for_training": true
}
```

### 1.3 Frontend: Annotation UI

**New Angular components:**
- `components/yolo-training/` - Training dashboard
- `components/yolo-annotation/` - Box annotation interface (can reuse Fabric.js from CuReD)

**Training Dashboard Features:**
1. Dataset selector (AHw, CAD, custom)
2. Upload images for annotation
3. Annotation canvas (draw/edit boxes, assign classes)
4. Export to YOLO format
5. Training configuration panel
6. Real-time training progress (loss curves, mAP)
7. Model management (list, download, delete)

**Annotation Workflow:**
```
1. User uploads PDF page images
2. User draws bounding boxes on Fabric.js canvas
3. User assigns class labels to each box
4. System saves in YOLO format
5. Repeat until sufficient data (minimum checker)
6. User clicks "Train" → backend starts training
7. Progress shown via SSE
8. Model saved and available for inference
```

### 1.4 Minimum Data Checker

Before enabling the "Train" button, validate:

```python
MINIMUM_REQUIREMENTS = {
    "total_images": 20,           # At least 20 annotated images
    "val_split": 0.1,             # 10% for validation
    "min_instances_per_class": 10, # Each class needs 10+ examples
}

def check_training_ready(dataset_name: str) -> dict:
    stats = get_dataset_stats(dataset_name)
    issues = []

    if stats["total_images"] < MINIMUM_REQUIREMENTS["total_images"]:
        issues.append(f"Need {MINIMUM_REQUIREMENTS['total_images']} images, have {stats['total_images']}")

    for class_name, count in stats["class_distribution"].items():
        if count < MINIMUM_REQUIREMENTS["min_instances_per_class"]:
            issues.append(f"Class '{class_name}' needs {MINIMUM_REQUIREMENTS['min_instances_per_class']} examples, has {count}")

    return {
        "ready": len(issues) == 0,
        "issues": issues,
        "stats": stats
    }
```

### 1.5 Docker Integration

Add to `server/Dockerfile`:
```dockerfile
# Add YOLO dependencies
RUN pip install ultralytics pdf2image pillow

# Pre-download base model
RUN python -c "from ultralytics import YOLO; YOLO('yolov8s.pt')"
```

Add to `docker-compose.yml`:
```yaml
services:
  server:
    volumes:
      - yolo_data:/app/data/yolo
    environment:
      - YOLO_MODELS_PATH=/app/data/yolo/models
      - YOLO_DATASETS_PATH=/app/data/yolo/datasets

volumes:
  yolo_data:
```

---

## Phase 2: YOLO + Kraken Integration (CuReD)

### Goal
Integrate YOLO layout detection into CuReD workflow: auto-detect boxes → OCR each box.

### 2.1 Backend: Layout Detection Endpoint

**New endpoint in `server/src/api/routers/cured.py`:**

```python
@router.post("/detect-layout")
async def detect_layout(
    image: UploadFile,
    model: str = "default",  # or "ahw_layout_v1", "cad_layout_v1"
    confidence: float = 0.25
) -> LayoutDetectionResponse:
    """
    Detect layout regions in an image using YOLO.
    Returns bounding boxes with class labels.
    """
    # Load YOLO model
    yolo_model = get_yolo_model(model)

    # Run inference
    results = yolo_model.predict(image, conf=confidence)

    # Convert to response format
    regions = []
    for box in results[0].boxes:
        regions.append({
            "class_name": CLASS_NAMES[int(box.cls)],
            "class_id": int(box.cls),
            "confidence": float(box.conf),
            "bbox": {
                "x": float(box.xyxy[0][0]),
                "y": float(box.xyxy[0][1]),
                "width": float(box.xyxy[0][2] - box.xyxy[0][0]),
                "height": float(box.xyxy[0][3] - box.xyxy[0][1])
            }
        })

    return {"regions": regions, "model_used": model}
```

### 2.2 Backend: Combined Layout + OCR Endpoint

```python
@router.post("/process-page")
async def process_page(
    image: UploadFile,
    layout_model: str = "default",
    ocr_model: str = "default",
    confidence: float = 0.25
) -> PageProcessingResponse:
    """
    Full pipeline: detect layout → OCR each region.
    """
    # Step 1: Detect layout
    layout = await detect_layout(image, layout_model, confidence)

    # Step 2: OCR each region
    img = Image.open(image.file)
    results = []

    for region in layout["regions"]:
        # Crop region
        bbox = region["bbox"]
        crop = img.crop((bbox["x"], bbox["y"],
                         bbox["x"] + bbox["width"],
                         bbox["y"] + bbox["height"]))

        # Run Kraken OCR
        text = await run_kraken_ocr(crop, ocr_model)

        results.append({
            **region,
            "text": text
        })

    return {
        "regions": results,
        "layout_model": layout_model,
        "ocr_model": ocr_model
    }
```

### 2.3 Frontend: CuReD Integration

**Modify `fabric-canvas.component.ts`:**

```typescript
// New service
import { LayoutDetectionService } from '../../services/layout-detection.service';

// Add to toolbar
async autoDetectLayout() {
    const imageData = this.canvas.toDataURL('image/png');

    // Show loading
    this.isDetecting = true;

    try {
        const regions = await this.layoutService.detectLayout(imageData, this.selectedModel);

        // Clear existing boxes (optional, or merge)
        // this.clearBoxes();

        // Add detected boxes to canvas
        for (const region of regions) {
            this.addDetectedBox(region);
        }

        this.snackBar.open(`Detected ${regions.length} regions`, 'OK', {duration: 3000});
    } catch (error) {
        this.snackBar.open('Layout detection failed', 'OK', {duration: 3000});
    } finally {
        this.isDetecting = false;
    }
}

addDetectedBox(region: LayoutRegion) {
    const rect = new fabric.Rect({
        left: region.bbox.x,
        top: region.bbox.y,
        width: region.bbox.width,
        height: region.bbox.height,
        fill: 'transparent',
        stroke: this.getColorForClass(region.class_name),
        strokeWidth: 2,
        selectable: true,
        // Store metadata
        data: {
            class_name: region.class_name,
            class_id: region.class_id,
            confidence: region.confidence
        }
    });

    this.canvas.add(rect);
}

getColorForClass(className: string): string {
    const colors = {
        'entry': '#0000FF',
        'subentry': '#00FFFF',
        'guidewords': '#808080',
        'page_number': '#FFA500',
        'root_index': '#FF0000'
    };
    return colors[className] || '#00FF00';
}
```

**New service `layout-detection.service.ts`:**

```typescript
@Injectable({ providedIn: 'root' })
export class LayoutDetectionService {
    constructor(private http: HttpClient) {}

    detectLayout(imageData: string, model: string = 'default'): Observable<LayoutRegion[]> {
        const formData = new FormData();
        formData.append('image', this.dataURLtoBlob(imageData));
        formData.append('model', model);

        return this.http.post<{regions: LayoutRegion[]}>('/api/cured/detect-layout', formData)
            .pipe(map(res => res.regions));
    }

    processPage(imageData: string, layoutModel: string, ocrModel: string): Observable<ProcessedRegion[]> {
        const formData = new FormData();
        formData.append('image', this.dataURLtoBlob(imageData));
        formData.append('layout_model', layoutModel);
        formData.append('ocr_model', ocrModel);

        return this.http.post<{regions: ProcessedRegion[]}>('/api/cured/process-page', formData)
            .pipe(map(res => res.regions));
    }
}
```

**UI Changes:**

Add to CuReD toolbar:
- "Auto-detect Layout" button (magic wand icon)
- Model selector dropdown (default, ahw_layout, cad_layout)
- "Process All" button (detect + OCR in one step)

### 2.4 Workflow

```
User loads page in CuReD
         │
         ▼
┌─────────────────────────────────────────┐
│  Click "Auto-detect Layout"             │
│  (or auto-run on page load if enabled)  │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  YOLO detects regions                   │
│  Boxes appear on canvas with colors     │
│  by class (entry=blue, etc.)            │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  User reviews/adjusts boxes             │
│  (resize, delete, add missing)          │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Click "OCR Selected" or "OCR All"      │
│  Kraken processes each box              │
│  Text appears in editor panel           │
└─────────────────────────────────────────┘
```

---

## Phase 3: CuReD Dict (Specialized Dictionary Models)

### Goal
Create pre-trained, optimized models specifically for AHw and CAD dictionaries.

### 3.1 Model Training Plan

**AHw (Akkadisches Handwörterbuch):**
- Source: PDF scans of AHw volumes
- Training data: 50-100 annotated pages
- Classes: entry, subentry, guidewords, page_number, root_index
- Target mAP: >95%

**CAD (Chicago Assyrian Dictionary):**
- Source: PDF scans of CAD volumes
- Training data: 50-100 annotated pages
- Classes: entry, subentry, guidewords, page_number, etymology, references
- Target mAP: >95%

### 3.2 Pre-trained Model Distribution

**Option A: Bundle with Docker image**
```dockerfile
# In server/Dockerfile
COPY models/ahw_layout_v1.pt /app/models/
COPY models/cad_layout_v1.pt /app/models/
COPY models/ahw_ocr.mlmodel /app/models/
COPY models/cad_ocr.mlmodel /app/models/
```

**Option B: Download on first use**
```python
MODEL_REGISTRY = {
    "ahw_layout_v1": {
        "url": "https://github.com/user/ben-app-models/releases/download/v1/ahw_layout_v1.pt",
        "sha256": "abc123..."
    },
    "cad_layout_v1": {
        "url": "https://github.com/user/ben-app-models/releases/download/v1/cad_layout_v1.pt",
        "sha256": "def456..."
    }
}

async def ensure_model_downloaded(model_name: str) -> Path:
    model_path = MODELS_DIR / f"{model_name}.pt"
    if not model_path.exists():
        await download_model(MODEL_REGISTRY[model_name])
    return model_path
```

### 3.3 Dictionary-Specific OCR (Kraken)

Train Kraken models optimized for dictionary text:

**AHw OCR Model:**
- Handles German text with Akkadian transliteration
- Special characters: ā, ē, ī, ū, š, ṣ, ṭ, ḫ, etc.
- Abbreviations: AHw, CAD, Gt, Gtn, Š, Št, N, etc.

**CAD OCR Model:**
- Similar character set
- English definitions
- More reference abbreviations

### 3.4 Frontend: Dictionary Mode

Add "Dictionary Mode" toggle in CuReD:

```typescript
// When Dictionary Mode is ON:
// - Auto-select appropriate YOLO model based on document
// - Auto-select appropriate Kraken model
// - Enable dictionary-specific post-processing (abbreviation expansion, etc.)

dictionaryModes = [
    { name: 'AHw', layoutModel: 'ahw_layout_v1', ocrModel: 'ahw_ocr_v1' },
    { name: 'CAD', layoutModel: 'cad_layout_v1', ocrModel: 'cad_ocr_v1' },
    { name: 'Custom', layoutModel: 'default', ocrModel: 'default' }
];
```

---

## Phase 4: Trainable VLM (New System)

### Goal
Develop a Vision-Language Model that performs layout detection AND OCR in a single pass.

### 4.1 Model Selection

**Candidate VLMs:**

| Model | Parameters | VRAM Required | Strengths |
|-------|------------|---------------|-----------|
| **Qwen2-VL** | 2B-72B | 8GB-80GB | Excellent document understanding |
| **PaliGemma** | 3B | 8GB | Google's multimodal, fine-tunable |
| **Florence-2** | 0.2B-0.8B | 4GB | Microsoft, document-focused |
| **Donut** | 200M | 4GB | Document understanding without OCR |
| **Nougat** | 250M | 4GB | Academic document parsing |

**Recommended: Florence-2 or Qwen2-VL-2B**
- Fits on university GPUs (A100, V100)
- Fine-tunable for custom domains
- Good balance of capability vs resource requirements

### 4.2 Training Infrastructure

**Options:**

1. **University HPC Cluster**
   - Submit SLURM jobs
   - Use available A100/V100 GPUs
   - Export trained model for local inference

2. **Cloud Training (AWS/GCP/Azure)**
   - Spot instances for cost efficiency
   - Train on demand
   - Store models in cloud storage

3. **Hugging Face AutoTrain**
   - Managed training service
   - Upload data, get trained model
   - No infrastructure management

### 4.3 Training Data Format

VLMs typically use instruction-style data:

```json
{
    "image": "page_001.png",
    "conversations": [
        {
            "from": "human",
            "value": "<image>\nExtract all dictionary entries from this page. For each entry, provide the headword, definition, and any sub-entries."
        },
        {
            "from": "gpt",
            "value": "## Entry 1\n**Headword:** qatāpu(m)\n**Definition:** to pluck, pick (fruit, etc.)\n**Sub-entries:**\n1) G: basic meaning...\n2) Gt: reciprocal...\n\n## Entry 2\n..."
        }
    ]
}
```

### 4.4 Integration Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        BEn-App                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐         ┌─────────────────┐            │
│  │    CuReD        │         │    VLM System   │            │
│  │  (YOLO+Kraken)  │         │   (New Name)    │            │
│  └────────┬────────┘         └────────┬────────┘            │
│           │                           │                      │
│           ▼                           ▼                      │
│  ┌─────────────────┐         ┌─────────────────┐            │
│  │ Layout Service  │         │  VLM Service    │            │
│  │ (local Docker)  │         │ (local/remote)  │            │
│  └─────────────────┘         └─────────────────┘            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**VLM can run:**
- Locally (if GPU available)
- Remote API (university server, cloud)
- Hybrid (local for small models, remote for large)

### 4.5 API Design

```python
# POST /api/vlm/process
{
    "image": "<base64>",
    "model": "florence-2-ft-ahw",
    "task": "extract_entries",  # or "detect_layout", "ocr_region"
    "options": {
        "output_format": "json",  # or "markdown", "xml"
        "include_coordinates": true
    }
}

# Response
{
    "entries": [
        {
            "headword": "qatāpu(m)",
            "bbox": [100, 200, 400, 350],
            "definition": "to pluck, pick...",
            "sub_entries": [...]
        }
    ],
    "raw_text": "...",
    "confidence": 0.94
}
```

### 4.6 Training Pipeline

```
1. Data Preparation
   ├── Export annotated pages from CuReD
   ├── Convert to VLM training format
   └── Split train/val/test

2. Training
   ├── Upload to training infrastructure
   ├── Fine-tune base VLM
   ├── Monitor training metrics
   └── Export best checkpoint

3. Evaluation
   ├── Test on held-out pages
   ├── Compare with YOLO+Kraken baseline
   └── Human review of outputs

4. Deployment
   ├── Convert to inference format (ONNX, TensorRT)
   ├── Deploy to server or edge
   └── Integrate with frontend
```

---

## Implementation Timeline

| Phase | Tasks | Dependencies |
|-------|-------|--------------|
| **Phase 1** | YOLO frontend training | None |
| **Phase 2** | YOLO+Kraken integration | Phase 1 (for trained models) |
| **Phase 3** | CuReD Dict models | Phase 1 + 2 (need training UI + integration) |
| **Phase 4** | VLM system | Independent (can start research in parallel) |

### Suggested Order

1. **Start Phase 1**: Build training UI, train AHw YOLO model
2. **Start Phase 2**: Integrate YOLO into CuReD (use trained AHw model)
3. **Continue Phase 1**: Train CAD YOLO model
4. **Complete Phase 3**: Bundle models, create dictionary modes
5. **Research Phase 4**: Prototype VLM, evaluate feasibility
6. **Implement Phase 4**: Build VLM training pipeline and integration

---

## File Structure Summary

```
server/
├── src/
│   ├── api/
│   │   └── routers/
│   │       ├── yolo.py          # Phase 1: YOLO training API
│   │       └── vlm.py           # Phase 4: VLM API
│   ├── handlers/
│   │   ├── yolo_training_handler.py
│   │   └── vlm_handler.py
│   └── clients/
│       ├── yolo_client.py
│       └── vlm_client.py
├── data/
│   ├── yolo/
│   │   ├── datasets/
│   │   └── models/
│   └── vlm/
│       ├── training_data/
│       └── models/
└── Dockerfile

app/
├── src/
│   └── app/
│       ├── components/
│       │   ├── yolo-training/    # Phase 1: Training dashboard
│       │   └── vlm-interface/    # Phase 4: VLM UI
│       └── services/
│           ├── layout-detection.service.ts  # Phase 2
│           └── vlm.service.ts               # Phase 4
└── ...
```

---

## Open Questions

1. **VLM Model Choice**: Which base model to use? (Recommend evaluating Florence-2 and Qwen2-VL-2B)
2. **VLM System Name**: What to call the new VLM-based system?
3. **Training Data Sharing**: How to handle model/data sharing between AHw and CAD?
4. **Remote Training**: Which infrastructure for VLM training? (University HPC vs cloud)
5. **Model Versioning**: How to track and manage model versions across deployments?

---

*Document created: January 2026*
*Project: BEn-app ML Pipeline*
