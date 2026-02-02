# BEn-App OCR Pipeline Plan (Updated January 2026)

## Overview

Two specialized OCR pipelines for different document types, both designed to run on consumer hardware.

**CuReD Pipeline:** `YOLO (optional) → Kraken OCR → Normalizer (optional)`

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BEn-App OCR Architecture                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────┐    ┌─────────────────────────────────────┐ │
│  │     Dictionary OCR          │    │          CuReD                       │ │
│  │     (AHw / CAD)             │    │     (Cuneiform Tablets)              │ │
│  ├─────────────────────────────┤    ├─────────────────────────────────────┤ │
│  │                             │    │                                      │ │
│  │  ┌─────────────────────┐   │    │  ┌─────────────────────┐            │ │
│  │  │ YOLOv8 (optional)   │   │    │  │ YOLOv8              │            │ │
│  │  │ Layout Detection    │   │    │  │ Layout Detection    │            │ │
│  │  └──────────┬──────────┘   │    │  └──────────┬──────────┘            │ │
│  │             ▼              │    │             ▼                        │ │
│  │  ┌─────────────────────┐   │    │  ┌─────────────────────┐            │ │
│  │  │ DeepSeek-OCR-2      │   │    │  │ Kraken 6.0.3        │            │ │
│  │  │ (3B params)         │   │    │  │ (trainable)         │            │ │
│  │  └─────────────────────┘   │    │  └─────────────────────┘            │ │
│  │                             │    │                                      │ │
│  │  VRAM: 6-8GB               │    │  VRAM: 2-4GB (CPU possible)         │ │
│  │  Fine-tunable: LoRA        │    │  Fine-tunable: ketos train          │ │
│  └─────────────────────────────┘    └─────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline 1: Dictionary OCR (DeepSeek-OCR-2)

### Purpose
OCR for Assyriological dictionaries (AHw, CAD) - typed German/English text with special characters.

### Technology Stack

| Component | Technology | Requirements |
|-----------|------------|--------------|
| Layout Detection | YOLOv8s (optional) | CPU or 2GB VRAM |
| OCR | DeepSeek-OCR-2 (3B) | 6-8GB VRAM (4GB with 4-bit quantization) |
| Fine-tuning | Unsloth + LoRA | 8GB VRAM or Colab (free) |

### Hardware Requirements

| Mode | Minimum | Recommended |
|------|---------|-------------|
| Inference (4-bit) | 4GB VRAM | 8GB VRAM |
| Inference (8-bit) | 8GB VRAM | 12GB VRAM |
| Fine-tuning (LoRA) | 8GB VRAM | 16GB VRAM |
| Fine-tuning (full) | 24GB VRAM | 40GB VRAM |

### Model Update Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    Model Distribution Flow                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐                                               │
│  │ Base Model   │  deepseek-ai/DeepSeek-OCR-2                   │
│  │ (HuggingFace)│  Downloaded once, cached locally              │
│  └──────┬───────┘                                               │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐                                               │
│  │ Community    │  BEn-App releases fine-tuned adapters         │
│  │ LoRA Adapter │  for AHw/CAD periodically                     │
│  │ (GitHub)     │  ~50-100MB per adapter                        │
│  └──────┬───────┘                                               │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐                                               │
│  │ User's Local │  Users can further fine-tune with their       │
│  │ LoRA Adapter │  own corrections (stacks on community)        │
│  └──────────────┘                                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Features

- [x] Single-page OCR
- [ ] **Batch processing** (process entire PDF volumes)
- [ ] Column detection (YOLO-based)
- [ ] User corrections storage
- [ ] Fine-tuning data export
- [ ] Community model updates

---

## Pipeline 2: CuReD (YOLO + Kraken)

### Purpose
OCR for cuneiform tablet photographs - transliteration to Latin script.

### Technology Stack

| Component | Technology | Requirements |
|-----------|------------|--------------|
| Layout Detection | YOLOv8s (optional) | CPU or 2GB VRAM |
| OCR | Kraken 6.0.3 | CPU (slow) or 2-4GB VRAM |
| Normalization | Custom dictionary (optional) | None |
| Fine-tuning | ketos train | CPU or GPU |

### Hardware Requirements

| Mode | Minimum | Recommended |
|------|---------|-------------|
| Inference (CPU) | 4GB RAM | 8GB RAM |
| Inference (GPU) | 2GB VRAM | 4GB VRAM |
| Training (CPU) | 8GB RAM | 16GB RAM |
| Training (GPU) | 4GB VRAM | 8GB VRAM |

**CuReD runs on virtually any modern computer**, including laptops without dedicated GPUs.

### Model Update Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    Kraken Model Distribution                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐                                               │
│  │ Base Model   │  Pre-trained on general cuneiform             │
│  │ (bundled)    │  Included in Docker image                     │
│  └──────┬───────┘                                               │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐                                               │
│  │ Community    │  BEn-App releases improved models             │
│  │ Model        │  trained on pooled corrections                │
│  │ (GitHub)     │  ~10-50MB per model                           │
│  └──────┬───────┘                                               │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐                                               │
│  │ User's Local │  Users train on their own corrections         │
│  │ Model        │  via "Train Model" button in UI               │
│  └──────────────┘                                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Features

- [x] YOLO layout detection (98.9% mAP)
- [x] Kraken 6.0.3 OCR
- [x] User training from UI
- [x] Model versioning
- [x] **Normalizer** (post-OCR text correction)
- [ ] **Batch processing** (process multiple tablets)
- [ ] Community model sync

### Normalizer (Post-Processing)

The normalizer is an optional post-processing step that applies dictionary-based corrections to OCR output. It runs after Kraken OCR and fixes common recognition errors.

**Pipeline Flow:**
```
YOLO (optional) → Kraken OCR → Normalizer (optional)
```

**Built-in Corrections:**
| Pattern | Replacement | Description |
|---------|-------------|-------------|
| `qr` | `ar` | Common OCR misread |
| `^dis` | `Dis` | Capitalize at line start |
| `^diš` | `Diš` | Capitalize at line start |

**Features:**
- User-editable dictionary from the frontend UI
- Add custom replacement rules per project
- Enable/disable normalizer per OCR run
- Export/import normalization dictionaries

**Frontend UI:**
- Accessible via "Normalization Settings" in CuReD component
- Add, edit, and delete replacement rules
- Test rules against sample text
- Toggle normalization on/off

---

## Batch Processing (Both Pipelines)

### API Design

```python
# POST /api/v1/batch/dictionary-ocr
{
    "pdf_path": "/path/to/ahw_volume.pdf",
    "pages": [1, 2, 3, 4, 5],  # or "all"
    "model": "ahw_v1",  # LoRA adapter name
    "output_format": "text"  # or "json", "xml"
}

# Response (async job)
{
    "job_id": "batch_abc123",
    "status": "queued",
    "total_pages": 5
}

# GET /api/v1/batch/dictionary-ocr/{job_id}/status
{
    "job_id": "batch_abc123",
    "status": "processing",
    "progress": {
        "completed": 3,
        "total": 5,
        "current_page": 4
    }
}

# GET /api/v1/batch/dictionary-ocr/{job_id}/results
{
    "job_id": "batch_abc123",
    "status": "completed",
    "results": [
        {"page": 1, "text": "...", "processing_time_ms": 1234},
        {"page": 2, "text": "...", "processing_time_ms": 1156},
        ...
    ]
}
```

### Frontend UI

```
┌─────────────────────────────────────────────────────────────────┐
│  Batch Processing                                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Drop PDF here or click to browse                        │    │
│  │                                                          │    │
│  │  📄 AHw_Volume_1.pdf (245 pages)                        │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  Pages: [1] to [245]  or ☑ All pages                            │
│                                                                  │
│  Model: [▼ AHw Community v1.2 (recommended)]                    │
│         └─ AHw Community v1.2 (recommended)                     │
│            AHw Community v1.1                                   │
│            My Custom AHw (local)                                │
│                                                                  │
│  Output: ○ Plain Text  ● JSON  ○ XML (TEI)                      │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Processing: Page 47 / 245                                │   │
│  │  ━━━━━━━━━━━━━━━━░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  19%     │   │
│  │                                                           │   │
│  │  Estimated time remaining: ~45 min                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [ Cancel ]                              [ Download Results ]    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: DeepSeek-OCR-2 Integration (Current)
- [ ] Create DeepSeek-OCR-2 Docker service
- [ ] Backend API for single-page OCR
- [ ] Frontend Dictionary OCR component
- [ ] Test with AHw sample pages

### Phase 2: Batch Processing
- [ ] Backend batch job system (async)
- [ ] Progress tracking via SSE
- [ ] Frontend batch UI
- [ ] Export results (TXT, JSON, XML)

### Phase 3: Fine-tuning Pipeline
- [ ] Correction storage (MongoDB)
- [ ] Export training data format
- [ ] Unsloth fine-tuning notebook (Colab)
- [ ] LoRA adapter loading

### Phase 4: Community Models
- [ ] GitHub releases for model adapters
- [ ] Model download/update in app
- [ ] Version management UI

---

## File Structure

```
server/
├── src/
│   ├── api/routers/
│   │   ├── dictionary_ocr.py      # DeepSeek endpoints
│   │   ├── cured.py               # Existing CuReD
│   │   ├── batch.py               # Batch processing
│   │   └── yolo_training.py       # YOLO training
│   ├── handlers/
│   │   ├── deepseek_handler.py    # DeepSeek logic
│   │   ├── batch_handler.py       # Batch job management
│   │   └── normalizer_handler.py  # Normalizer logic
│   ├── clients/
│   │   └── deepseek_client.py     # DeepSeek API client
│   └── services/
│       ├── kraken_training_service.py  # ✅ Exists
│       ├── normalizer_service.py  # Post-OCR text normalization
│       └── batch_service.py       # Batch job queue

deepseek-ocr/                      # NEW Docker service
├── Dockerfile
├── requirements.txt
├── src/
│   ├── main.py                    # FastAPI service
│   └── inference.py               # DeepSeek inference

app/src/app/
├── components/
│   ├── dictionary-ocr/            # ✅ Exists (update)
│   ├── batch-processing/          # NEW
│   └── cured/                     # ✅ Exists
│       └── normalizer-settings/   # NEW - user dictionary UI
└── services/
    ├── deepseek-ocr.service.ts    # NEW
    ├── normalizer.service.ts      # NEW - normalizer API
    └── batch.service.ts           # NEW
```

---

## Docker Compose Addition

```yaml
# DeepSeek OCR Service
deepseek-ocr:
  build:
    context: ./deepseek-ocr
  container_name: deepseek-ocr
  ports:
    - 5004:5004
  networks:
    - backend
  volumes:
    - deepseek-models:/app/models
    - deepseek-cache:/root/.cache/huggingface
  environment:
    - MODEL_ID=deepseek-ai/DeepSeek-OCR-2
    - QUANTIZATION=4bit  # or 8bit, none
    - MAX_BATCH_SIZE=4
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
    restart_policy:
      condition: on-failure
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:5004/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 120s

volumes:
  deepseek-models:
    driver: local
  deepseek-cache:
    driver: local
```

---

## Comparison Summary

| Feature | Dictionary OCR | CuReD |
|---------|---------------|-------|
| **Model** | DeepSeek-OCR-2 (3B) | Kraken 6.0.3 |
| **Input** | Dictionary pages (AHw/CAD) | Cuneiform tablet photos |
| **Output** | German/English text | Latin transliteration |
| **Min VRAM** | 4GB (4-bit) | 0GB (CPU) |
| **Rec VRAM** | 8GB | 4GB |
| **Fine-tuning** | LoRA (Colab/local) | ketos train (local) |
| **Normalizer** | Planned | Yes (user-editable) |
| **Batch** | Planned | Planned |
| **Runs on laptop** | Yes (with GPU) | Yes (any) |

---

## Removed/Deprecated Plans

The following have been superseded by this plan:

- ~~VLM_OCR_IMPLEMENTATION_PLAN.md~~ (LLaVA/dots.ocr approach - too resource-heavy)
- ~~ML_PIPELINE_PLAN.md~~ (consolidated into this document)

Retained documents:
- [KRAKEN_TRAINING_PLAN.md](KRAKEN_TRAINING_PLAN.md) - Details on Kraken training UI
- [YOLO_LAYOUT_DETECTION.md](YOLO_LAYOUT_DETECTION.md) - YOLO training guide

---

*Document created: January 30, 2026*
*Replaces: VLM_OCR_IMPLEMENTATION_PLAN.md, ML_PIPELINE_PLAN.md*
