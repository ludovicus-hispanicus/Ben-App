# BEn App - Future Features Roadmap

This document outlines planned features for future development after the desktop app is working.

---

## Vision: BEn as OCR & Curation Platform

BEn is not just an OCR tool but a complete **curation platform** for Assyriological texts. The architecture follows a four-tier OCR strategy with a knowledge distillation loop that improves local models over time.

### Four-Tier OCR Architecture

| Tier | Model | Hardware | Use Case | Trainable |
|------|-------|----------|----------|-----------|
| **Manual Import** | External (paste) | None | User brings OCR from any source (web AI, other tools) | N/A |
| **Fallback** | Kraken | CPU only | Offline, bulk processing, guaranteed availability | Yes (easy) |
| **Local GPU** | Qwen3-VL / Nemotron + YOLO | 6-8GB GPU | Better quality, markdown output, entry detection | Yes |
| **Premium** | Cloud APIs (Claude, Gemini, GPT, Grok) | None (cloud) | Best quality, latest models, special characters | No |

### Local VLM Model Comparison

| Model | Distribution | Markdown | Trainable | VRAM (4-bit) | Notes |
|-------|--------------|----------|-----------|--------------|-------|
| **Qwen3-VL-235B** | Ollama (`qwen3-vl:235b-cloud`) | ✅ Yes | ❌ No (API) | Cloud | Best quality via Ollama |
| **Qwen3-VL-2B/4B** | HuggingFace (local) | ✅ Yes | ✅ Yes (LoRA) | 4-6GB | Trainable, fits 8GB GPU |
| **Qwen2-VL-7B** | Ollama (`qwen2-vl:7b`) | ✅ Yes | ✅ Yes (LoRA) | ~4.5GB | Local, trainable |
| **DeepSeek-OCR** | Ollama (`deepseek-ocr`) | ❌ No | ❌ No | ~6.7GB | Plain text only |
| **Nemotron-Parse** | HuggingFace (WSL2/Docker) | ✅ Yes | ❌ No | ~3.5GB | Best quality, own impl. |

**Recommended prompts for markdown output (Qwen):**
```
This is a dictionary entry from AHw (Akkadisches Handwörterbuch).
OCR this image with careful attention to typography:
- The headword at the beginning is in BOLD - use **bold**
- Akkadian words and forms are in ITALIC - use *italic* for ALL of them
- German translations are in regular text
- Apply formatting consistently throughout the ENTIRE text, not just the first line.

Output the complete text with markdown formatting.
```

**Manual Import ("Bring Your Own OCR"):**
- User performs OCR externally (Gemini web, ChatGPT, Claude.ai, etc.)
- Pastes result into BEn
- BEn handles parsing, curation, and correction
- No API keys required - uses free web interfaces
- Same curation workflow, just different input source

### Knowledge Distillation Loop

```
┌─────────────────────────────────────────────────────────────┐
│                    DISTILLATION CYCLE                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   Cloud API ─────┐                                          │
│   (via API)      │                                          │
│                  ├──► User Curation ──────► Training Data   │
│   Manual Import ─┤    (corrections,         (curated        │
│   (paste from    │     annotations)          pairs)         │
│    web AI)       │          │                    │          │
│                  │          ▼                    ▼          │
│   Local VLM ─────┘   Kraken / Nemotron ◄────── Fine-tune    │
│                      (free, improving)                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**All input sources feed the same curation workflow → training data → model improvement.**

**Benefits:**
- Models improve with each curation cycle
- Reduces dependency on expensive APIs over time
- Community contributions benefit everyone
- Specialized for Assyriological content

### eBL Integration Goals

- **Export**: Standard formats (ATF, TEI Lex-0) compatible with eBL
- **Import**: eBL-ATF rules for validation and normalization
- **Bidirectional**: BEn as "OCR frontend" for eBL ecosystem

---

## Phase 1: Desktop App Foundation ✅ (Current Focus)

- [ ] Verify babylon-pub Electron wrapper works with current BEn-app
- [ ] Ensure Docker images are up to date
- [ ] Test full workflow on Windows

---

## Phase 1.5: Standalone Desktop Installer

**Goal**: Create a simple installer (.exe) that users can download and run without technical setup.

### Architecture Decision: Electron + Ollama

After analysis, the recommended approach is **Electron app + Ollama integration**:

```
┌─────────────────────────────────────────────────────────────┐
│                    BEn Desktop Architecture                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   BEn Desktop (.exe)          Ollama (separate install)     │
│   ┌─────────────────┐         ┌─────────────────┐          │
│   │ Electron Shell  │         │ Ollama Server   │          │
│   │ Angular Frontend│ ◄─────► │ DeepSeek-OCR    │          │
│   │ Embedded Python │   HTTP  │ (6.7GB model)   │          │
│   │ (Kraken only)   │         │                 │          │
│   └─────────────────┘         └─────────────────┘          │
│         ~150MB                    ~500MB + models           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Why Electron + Ollama:**
- Ollama has official Windows/Mac/Linux installers
- Ollama handles GPU/CUDA complexity automatically
- Models downloaded on-demand (not bundled)
- Clean separation: BEn = UI/curation, Ollama = ML inference
- Easy model updates without app reinstall

### Alternative Approaches (Not Recommended)

| Approach | Why Not |
|----------|---------|
| Full Python bundle | 5-15GB installer, CUDA bundling nightmares |
| Docker Desktop requirement | Too complex for non-technical users |
| Web-only | Loses offline capability |

### Implementation Tasks

**BEn Desktop Installer:**
- [ ] Create electron-builder configuration for Windows/Mac/Linux
- [ ] Bundle minimal Python runtime for Kraken (CPU fallback)
- [ ] Auto-detect Ollama installation on startup
- [ ] Prompt user to install Ollama if not found
- [ ] First-run wizard to download models

**Ollama Integration:**
- [x] Create `server/src/services/ollama_ocr_service.py` - Ollama client ✅
- [x] Health check endpoint (`is_available()`, `get_status()`) ✅
- [x] Model availability check (`is_model_available()`) ✅
- [ ] Graceful fallback to Kraken if Ollama unavailable

**Installer Features:**
- [ ] Windows: NSIS or electron-builder squirrel installer
- [ ] macOS: DMG with drag-to-Applications
- [ ] Linux: AppImage or .deb package
- [ ] Auto-updater for future versions

### User Experience

**First-time setup:**
```
1. User downloads BEn-Desktop-Setup.exe (~150MB)
2. Runs installer → BEn installed
3. First launch:
   - "Ollama not detected. Install for best OCR quality?"
   - [Install Ollama] [Use CPU-only mode]
4. If Ollama chosen:
   - Opens Ollama download page OR auto-downloads
   - After Ollama installed: "Download DeepSeek-OCR model? (6.7GB)"
5. Ready to use!
```

**Returning user:**
```
1. Launch BEn Desktop
2. Auto-connects to local Ollama
3. Ready in seconds
```

### File Structure

```
BEn-Desktop/
├── electron/
│   ├── main.js                 # Electron main process
│   ├── preload.js              # Security bridge
│   └── ollama-check.js         # Detect/launch Ollama
├── python-runtime/             # Embedded Python (minimal)
│   ├── python.exe
│   └── kraken/                 # Kraken for CPU fallback
├── app/                        # Angular build output
│   └── dist/
├── server/                     # Python server (packaged)
│   └── main.py
└── resources/
    └── models/                 # Kraken models only (~50MB)
```

---

## Phase 2: Remove Authentication

**Goal**: Allow open access without login requirement.

### Backend Changes
- `server/src/auth/auth_bearer.py` - Disable JWT validation or make optional
- `server/src/api/routers/*.py` - Remove `Depends(JWTBearer())` from endpoints
- `server/src/handlers/users_handler.py` - Keep for optional user tracking

### Frontend Changes
- `app/src/app/auth/` - Remove login requirement
- `app/src/app/interceptors/auth.interceptor.ts` - Make token optional
- `app/src/app/home/` - Skip login screen, go directly to main app

### Notes
- Consider keeping optional user identification for tracking contributions
- Could use anonymous session IDs instead

---

## Phase 3: Simplify Output Format

**Goal**: Replace restrictive line-by-line approach with flexible TXT export for training.

### Current Problem
- Output is structured in rigid line-by-line format
- Hard to modify for retraining purposes
- Too restrictive for data collection

### Proposed Solution
- Add "Export as TXT" button
- Simple format: image path + full transliteration text
- Allow free-form editing before export

### Files to Modify
- `server/src/handlers/texts_handler.py` - Add simple export method
- `server/src/api/routers/text.py` - Add TXT export endpoint
- `app/src/app/amendment/` - Add export button to UI

### Export Format Example
```
# text_id: 123
# image: user_upload/123.png
# exported: 2026-01-26

a-na {d}UTU EN GAL-i
EN-ia ŠEŠ-ia
um-ma {m}PN ARAD-ka-a-ma

---
[corrections]
line 1, pos 3: GAL → LUGAL (certainty: ?)
```

---

## Phase 4: Email Export for Training Data

**Goal**: Automatically send user corrections to your email for model retraining.

### Backend Changes

**New files:**
- `server/src/handlers/export_handler.py` - SMTP logic, queue management
- `server/src/api/routers/export.py` - Export API endpoints
- `server/src/api/dto/export_dto.py` - Request/response models

**Modify:**
- `server/src/handlers/texts_handler.py` - Queue corrections on save
- `server/src/handlers/new_texts_handler.py` - Queue transliterations on save
- `server/src/main.py` - Register export router

### Frontend Changes

**New files:**
- `app/src/app/settings/settings.component.ts` - Settings page
- `app/src/app/services/export.service.ts` - Export API client

**Modify:**
- `app/src/app/app-routing.module.ts` - Add settings route
- Navigation - Add settings link

### Database
```javascript
// MongoDB: export_queue collection
{
  data_type: "correction" | "transliteration",
  data: { /* correction data */ },
  created_at: ISODate,
  status: "pending" | "exported"
}

// MongoDB: settings collection
{
  _id: "smtp_config",
  host: "smtp.gmail.com",
  port: 587,
  username: "encrypted",
  password: "encrypted",
  recipient: "training@your-domain.com"
}
```

### Export JSON Format
```json
{
  "version": "1.0",
  "exportDate": "2026-01-26T10:00:00Z",
  "corrections": [...],
  "transliterations": [...],
  "images": [{"name": "...", "base64": "..."}]
}
```

---

## Phase 5: Add Local VLM for Dictionary

**Goal**: Integrate a local Vision Language Model (like LLaVA) for cuneiform sign dictionary/lookup.

### Model Options

| Model | Size | Quality | Notes |
|-------|------|---------|-------|
| LLaVA 1.5 7B | ~7GB | Good | Balanced size/quality |
| LLaVA 1.5 13B | ~13GB | Better | Higher quality, slower |
| Qwen-VL | ~10GB | Good | Alternative option |

### Architecture

```
User selects sign region → Crop image
           ↓
    Send to VLM endpoint
           ↓
    VLM analyzes sign
           ↓
    Return: sign name, reading, meaning, parallels
```

### Backend Changes

**New files:**
- `server/src/handlers/vlm_handler.py` - VLM inference logic
- `server/src/api/routers/dictionary.py` - Dictionary endpoints

**Dependencies:**
- `transformers` - For loading models
- `torch` - Already installed
- `accelerate` - For efficient inference

### Frontend Changes

**New component:**
- `app/src/app/dictionary/` - Dictionary lookup UI
- Selection tool to crop sign from image
- Results display with sign information

### Endpoints
```
POST /api/v1/dictionary/lookup
  - Input: cropped image (base64)
  - Output: { sign_name, readings, meaning, examples }

GET /api/v1/dictionary/search?query=LUGAL
  - Text-based search in sign database
```

### Docker Considerations
- VLM models are large (~7-13GB)
- May need separate container or volume for models
- Consider lazy loading (download on first use)

---

---

## Phase 6: Four-Tier OCR Implementation

**Goal**: Implement the four-tier OCR architecture with model selection and flexible input options.

### Tier 0: Manual Import ("Bring Your Own OCR")

**Purpose:** Allow users to paste OCR results from external sources (no generation, only curation).

**Use Cases:**
- User has no API keys but can use Gemini/ChatGPT/Claude web interfaces for free
- User has OCR from another tool (ABBYY, Tesseract, etc.)
- User wants to import existing transliterations for curation
- Testing/comparison of different OCR sources

**Features:**
- [ ] Paste text area for manual OCR input
- [ ] Option to associate with uploaded image (for side-by-side curation)
- [ ] Parse pasted text into line/entry structure
- [ ] Same curation workflow as auto-generated OCR
- [ ] Source tagging (track where OCR came from for quality analysis)

**Implementation:**
```
app/src/app/components/manual-import/     - Paste UI component
server/src/handlers/manual_import.py      - Parse and store pasted text
server/src/api/routers/manual_import.py   - Endpoints
```

**Workflow:**
```
User uploads image ──► User copies image to external AI (web)
                              ↓
                       External AI generates OCR
                              ↓
                       User copies result
                              ↓
                       Pastes into BEn ──► Curation UI
```

---

### Tier 1: Cloud APIs (Priority - Immediate Value)

**Supported Services:**
- Claude (Anthropic) - Excellent for special characters
- Gemini (Google) - Good multimodal understanding
- GPT-4 Vision (OpenAI) - Strong general OCR
- Grok (xAI) - Alternative option

**Implementation:**
```
app/src/app/services/cloud-ocr.service.ts    - API client abstraction
server/src/handlers/cloud_ocr_handler.py     - Backend proxy for API keys
server/src/api/routers/cloud_ocr.py          - Endpoints
```

**Features:**
- [ ] API key management (secure storage)
- [ ] Provider selection in UI
- [ ] Cost tracking per request
- [ ] Rate limiting and queuing

### Tier 2: Local VLM (Qwen3-VL / Nemotron + YOLO)

**Models:**

| Model | Distribution | Markdown | Trainable | VRAM | Notes |
|-------|--------------|----------|-----------|------|-------|
| **Qwen3-VL-235B** | Ollama (cloud API) | ✅ Yes | ❌ No | Cloud | Best quality, no training |
| **Qwen3-VL-2B/4B** | HuggingFace (local) | ✅ Yes | ✅ Yes (LoRA) | 4-6GB | Fits 8GB GPU, trainable |
| **Qwen2-VL-7B** | Ollama (local) | ✅ Yes | ✅ Yes (LoRA) | 4.5GB | Runs on 8GB GPU |
| **Nemotron-Parse** | HuggingFace (WSL2/Docker) | ✅ Yes | ❌ No | 3.5GB | Best quality, own impl. |
| **DeepSeek-OCR** | Ollama (local) | ❌ No | ❌ No | 6.7GB | Plain text only |
| **YOLO** | Own impl. | N/A | ✅ Yes | <1GB | Entry detection |

**Qwen3-VL Local Training (for 8GB GPU):**
```python
from unsloth import FastVisionModel

# Load Qwen3-VL-2B or 4B with 4-bit quantization
model, tokenizer = FastVisionModel.from_pretrained(
    "Qwen/Qwen3-VL-2B",  # or Qwen/Qwen3-VL-4B
    load_in_4bit=True,
)

# Add LoRA adapters (70% less VRAM, 2x faster)
model = FastVisionModel.get_peft_model(model, r=16, lora_alpha=16)

# Train on AHw image → markdown pairs
trainer.train()
```

**Nemotron-Parse Setup (not in Ollama):**
```bash
# Option 1: WSL2 (recommended for Windows)
wsl -d Ubuntu
pip install transformers torch accelerate
python -c "from transformers import AutoModelForVision2Seq; AutoModelForVision2Seq.from_pretrained('nvidia/NVIDIA-Nemotron-Parse-v1.1')"

# Option 2: Docker
docker run --gpus all -p 8080:8080 ben-nemotron
```

**Pipeline:**
```
Full Page Image
      ↓
   YOLO Detection ──► Entry bounding boxes
      ↓
   Crop entries
      ↓
   VLM OCR (Qwen3/Nemotron) ──► Text + markdown formatting
      ↓
   Output to curation UI
```

**Implementation:**
- [x] `server/src/services/nemotron_ocr_service.py` - Nemotron integration (HuggingFace)
- [x] `server/src/services/deepseek_ocr_service.py` - DeepSeek integration (Ollama)
- [x] `server/src/services/qwen_ocr_service.py` - Qwen2-VL integration
- [x] `server/src/services/ollama_ocr_service.py` - Generic Ollama client (Qwen3-VL, DeepSeek)
- [ ] YOLO entry detection integration in main pipeline
- [ ] Model switching in UI
- [ ] Prompt templates per dictionary type (AHw, CAD, etc.)

### Tier 3: Kraken Fallback (CPU)

**Purpose:** Guaranteed availability, offline operation, easy training.

**Features:**
- [ ] Kraken service integration
- [ ] CPU-only mode for low-resource environments
- [ ] Training pipeline for custom models
- [ ] Automatic fallback when GPU unavailable

---

## Phase 7: Curation Tools

**Goal**: Powerful editing and correction tools to speed up curation workflow.

### Core Features

- [ ] **Side-by-side view**: Image + transcription with synchronized scrolling
- [ ] **Bracket highlighting**: Visual indication of damaged/uncertain text
- [ ] **Sign palette**: Quick insertion of common cuneiform signs
- [ ] **Confidence highlighting**: Color-code low-confidence OCR segments
- [ ] **Diff view**: Compare original OCR vs corrected version

### Advanced Features

- [ ] **Keyboard shortcuts**: Vim-like navigation for power users
- [ ] **Batch operations**: Apply corrections across multiple texts
- [ ] **Version history**: Track all changes with rollback capability
- [ ] **Collaborative editing**: Multiple users on same document (future)

### Training Data Export

- [ ] **One-click export**: Generate training pairs from curated texts
- [ ] **Format options**: Kraken GT format, JSONL for VLM fine-tuning
- [ ] **Quality metrics**: Track curation coverage and confidence

---

## Phase 8: eBL Integration

**Goal**: Bidirectional integration with the electronic Babylonian Library.

### Export (BEn → eBL)

- [ ] ATF format export (standard Assyriology format)
- [ ] TEI Lex-0 XML for dictionary entries
- [ ] Validation against eBL-ATF rules before export

### Import (eBL → BEn)

- [ ] Import eBL-ATF validation rules
- [ ] Sign list synchronization
- [ ] Reference corpus for training

### API Integration

- [ ] eBL API client for direct submission
- [ ] Authentication with eBL credentials
- [ ] Status tracking for submitted texts

---

## Phase 9: Model Training Pipeline

**Goal**: Enable users to train/fine-tune local models from curated data.

### Kraken Training

- [ ] Ground truth export in Kraken format
- [ ] Training script integration
- [ ] Model versioning and comparison

### VLM Fine-tuning (Qwen2-VL)

- [ ] Training data format (image + TEI XML pairs)
- [ ] Unsloth/LoRA integration for efficient fine-tuning
- [ ] 8GB GPU support with 4-bit quantization
- [ ] Model evaluation metrics

### Distillation Pipeline

- [ ] Automatic collection of curated outputs
- [ ] Periodic retraining triggers
- [ ] A/B testing of model versions

---

## Priority Order

1. **Desktop App** (now) - Get it working
2. **Manual Import** (Phase 6.0) - Simple, immediate value, no API needed
3. **Cloud APIs** (Phase 6.1) - Best quality for those with API keys
4. **Curation Tools** (Phase 7) - Creates training data
5. **Remove Auth** - Opens access
6. **Local VLM** (Phase 6.2) - Benefits from curation data
7. **Simplify Output** - Better data collection
8. **Kraken Fallback** (Phase 6.3) - As training data accumulates
9. **eBL Integration** (Phase 8) - Once core is stable
10. **Training Pipeline** (Phase 9) - Long-term improvement
11. **VLM Dictionary** - Advanced feature

---

## Notes

- All features should be backward compatible
- Test each phase before moving to next
- Keep Docker images updated after each change
- Consider feature flags for gradual rollout
