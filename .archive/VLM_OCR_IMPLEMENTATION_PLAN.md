# VLM OCR Beta & Spacy Layout Integration - Implementation Plan

## Overview

1.  **VLM OCR**: Add **LLaVA 7B** (via Ollama) as a new "Dictionary OCR (Beta)" feature.
2.  **Layout Recognition**: Investigate and integrate **spacy-layout** (Docling) to improve column layout detection for Kraken/CuReD, replacing the default segmenter if superior.

**Goal**: Process AHw/CAD dictionary pages → Plain text output (XML later)

**Why Ollama + LLaVA?**
- Simple setup with automatic quantization
- Works on consumer GPUs (4GB+ VRAM)
- Good vision-language understanding
- Easy to swap models later (DeepSeek-OCR, etc.)
- Path to upgrade when more VRAM available

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Docker Compose                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  │   app    │    │  server  │───▶│  vlm-ocr │    │ layout-  │
│  │ Angular  │───▶│ FastAPI  │───▶│  Ollama  │    │ service  │
│  │ :8081    │    │  :5001   │    │  :5003   │    │ :5004    │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘
│                        │                │              ▲     │
│                        ▼                ▼              └─────┘ (3.10+)
│                  ┌──────────┐    ┌──────────┐              │
│                  │ mongodb  │    │  models  │              │
│                  │  :27018  │    │ (volume) │              │
│                  └──────────┘    └──────────┘              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Model: LLaVA 7B (via Ollama)

| Specification | Value |
|---------------|-------|
| Model | `llava:7b` |
| Parameters | 7B (quantized to 4-bit) |
| Strengths | General vision-language, OCR capable |
| VRAM Usage | ~3-4GB (quantized) |
| Fine-tuning | Can upgrade to DeepSeek-OCR later |

### Future Upgrade Path
When more VRAM is available (16GB+), can switch to:
- `deepseek-ai/DeepSeek-OCR` - Specialized for OCR, 57% better with fine-tuning
- `llava:34b` - Larger, more accurate

---

## Hardware Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| GPU VRAM | **4 GB** | 8+ GB |
| RAM | 8 GB | 16 GB |
| Disk | 5 GB | 10 GB (model cache) |

**Compatible GPUs:**
- NVIDIA RTX 2000 Ada (4GB) ✅ (your GPU!)
- NVIDIA RTX 3060/4060 (8GB) ✅
- NVIDIA RTX 3090/4090 (24GB) ✅ - can use larger models

---

## Files to Create

### Backend (server/)

| File | Purpose |
|------|---------|
| `src/api/routers/vlm_ocr.py` | New API router for VLM OCR endpoints |
| `src/handlers/vlm_ocr_handler.py` | Business logic for VLM processing |
| `src/clients/vlm_client.py` | HTTP client to call vLLM service |
| `src/api/dto/vlm_ocr_dto.py` | Request/response models |

### VLM Service (vlm-ocr/) - NEW DIRECTORY

| File | Purpose |
|------|---------|
| `Dockerfile` | Ollama + LLaVA container |
| `requirements.txt` | Python dependencies (if custom wrapper needed) |

### Frontend (app/)

| File | Purpose |
|------|---------|
| `src/app/components/dictionary-ocr/` | New component directory |
| `src/app/components/dictionary-ocr/dictionary-ocr.component.ts` | Main component |
| `src/app/components/dictionary-ocr/dictionary-ocr.component.html` | Template |
| `src/app/components/dictionary-ocr/dictionary-ocr.component.scss` | Styles |
| `src/app/services/vlm-ocr.service.ts` | API client service |

### Layout Service (layout-service/) - NEW DIRECTORY

| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.10+ container for Spacy Layout |
| `src/main.py` | FastAPI service exposing layout endpoints |
| `requirements.txt` | `spacy-layout`, `docling`, `fastapi`, `uvicorn` |

### Docker

| File | Purpose |
|------|---------|
| `electron/docker-compose.yml` | Add vlm-ocr AND layout-service |

---

## Files to Modify

### Backend

| File | Change |
|------|--------|
| `server/src/main.py` | Register vlm_ocr router |
| `server/requirements.txt` | Add httpx for async HTTP calls |

### Frontend

| File | Change |
|------|--------|
| `app/src/app/app-routing.module.ts` | Add dictionary-ocr route |
| `app/src/app/app.module.ts` | Import new component |
| `app/src/app/app.component.html` | Add navigation link with Beta badge |

---

## API Design

### Endpoint: POST /api/v1/vlm-ocr/process

**Request:**
```json
{
  "image": "base64_encoded_image",
  "source_type": "ahw" | "cad" | "generic",
  "output_format": "text" | "xml"
}
```

**Response:**
```json
{
  "success": true,
  "text": "jābinu d jānibu.\njābiš aB neben d jjābiš...",
  "processing_time_ms": 1234,
  "model": "deepseek-ocr"
}
```

### Endpoint: POST /api/v1/vlm-ocr/process-pdf

**Request:** multipart/form-data with PDF file + page number

**Response:** Same as above

### Endpoint: POST /api/v1/vlm-ocr/save-correction

**Request:**
```json
{
  "image_id": "ahw_411_001",
  "original_text": "...",
  "corrected_text": "...",
  "source_type": "ahw"
}
```

**Purpose:** Save corrections for future fine-tuning training data

---

## Layout Service API (Internal)

### Endpoint: POST /detect-columns

**Request:** Multipart image

**Response:**
```json
{
  "columns": [
    {"x": 10, "y": 10, "width": 400, "height": 1000},
    {"x": 420, "y": 10, "width": 400, "height": 1000}
  ]
}
```

---

## VLM Service Setup

### Using Ollama (Recommended for 4GB VRAM)

Ollama automatically handles quantization and runs efficiently on consumer GPUs:

```bash
# Pull and run locally
ollama pull llava:7b
ollama serve  # Starts on port 11434 by default
```

### Docker Setup (Production)

The vlm-ocr service uses Ollama in a container:

```bash
# Build and run
cd vlm-ocr
docker build -t vlm-ocr .
docker run --gpus all -p 5003:5003 -v ollama-models:/root/.ollama/models vlm-ocr
```

### API Call from Server

```python
# From FastAPI server
response = await client.post(
    "http://vlm-ocr:5003/api/generate",
    json={
        "model": "llava:7b",
        "prompt": PROMPT_DICTIONARY_OCR,
        "images": [image_base64],  # Raw base64, no data URI
        "stream": False,
        "options": {"temperature": 0.1}
    }
)
text = response.json()["response"]
```

### Future: Upgrade to DeepSeek-OCR

When 16GB+ VRAM is available:
1. Change model in `vlm_client.py`: `self.model = "deepseek-ocr"`
2. Pull model: `ollama pull deepseek-ocr`
3. Restart service

---

## Prompts for Dictionary OCR

### Normal Text - AHw/CAD (Phase 1)
```
You are an expert in reading Assyriological dictionaries (AHw, CAD).

Transcribe all text from this dictionary page image.

Rules:
1. Read left column completely first, then right column
2. Preserve reading order within each entry
3. Include all special characters exactly: š, ṣ, ṭ, ḫ, ā, ē, ī, ū
4. Headwords (lemmas) should be clearly identifiable
5. Preserve abbreviations as-is: RA, AfO, CT, ARM, etc.
6. Keep citation formats: ia-bi-le, ia-a-nu, etc.

Output plain text only, no markdown formatting.
```

### Layout-Aware Prompt
```
<|grounding|>Analyze the layout of this dictionary page.
Identify: columns, headwords (bold entries), citations, cross-references.
Then transcribe each column separately, preserving structure.
```

### XML Output (Phase 2 - Future)
```
You are an expert in reading Assyriological dictionaries.
Parse this dictionary page and output structured XML.

Use these tags:
- <page num="N"> wrapper for entire page
- <column n="1|2"> for each column
- <entry> for each dictionary entry
- <orth lang="akk"> for the headword (Akkadian lemma)
- <pos> for part of speech (v., s., adj., etc.)
- <gloss lang="de"> for German definitions
- <cit> for citations with <form> and <ref>
- <xr type="see"> for cross-references (q entries)

Example:
<entry>
  <orth lang="akk">jābinu</orth>
  <xr type="see">jānibu</xr>
</entry>
```

---

## Implementation Phases

### Phase 1: VLM & Layout Service Setup
1. Use `vlm-ocr/` directory for Ollama service.
2. Create `layout-service/` directory for Spacy Layout.
3. Create Dockerfile for layout-service (Python 3.11).
4. Implement layout detection endpoint using `spacy-layout`.
5. Add both services to `docker-compose.yml`.

### Phase 2: Backend Integration
1. Create `vlm_client.py` - HTTP client for vLLM/Ollama.
2. Create `layout_client.py` - HTTP client for Layout Service.
3. Update `cured_handler.py` to optionally use Layout Service for segmentation before calling Kraken.
    *   Fetch columns from Layout Service
    *   Convert to Kraken-compatible input (or use Python API)
4. Create `vlm_ocr_handler.py` for VLM logic.
5. Register routers.

### Phase 3: Frontend UI
1. Generate dictionary-ocr component
2. Add file upload (drag & drop for image/PDF)
3. Display OCR results in editable textarea
4. Add "Beta" badge to navigation
5. Connect to backend API
6. Add copy/export buttons

### Phase 4: Correction Storage (Training Data)
1. Add MongoDB collection for corrections
2. Create save-correction endpoint
3. Add "Submit Correction" button to UI
4. Store: original image, OCR output, user correction, timestamp

### Phase 5: Testing & Polish
1. Test with various AHw pages (different letters)
2. Test with CAD pages
3. Handle edge cases (large files, timeouts)
4. Add loading states and error handling
5. Performance optimization

---

## Docker Compose Addition

```yaml
# vlm-ocr - Ollama LLaVA VLM service
vlm-ocr:
  build:
    context: ../vlm-ocr/
  container_name: vlm-ocr
  ports:
    - 5003:5003
  networks:
    - backend
  volumes:
    - vlm-models:/root/.ollama/models
  environment:
    - OLLAMA_HOST=0.0.0.0:5003
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
    test: ["CMD", "curl", "-f", "http://localhost:5003/api/tags"]
    interval: 30s
    timeout: 10s
    retries: 5
    start_period: 120s  # Time for model download on first run
```

Add to volumes section:
```yaml
volumes:
  mongodata:
    driver: local
  server-storage:
    driver: local
  vlm-models:  # Ollama model cache
    driver: local
```

---

## VLM Dockerfile

```dockerfile
FROM ollama/ollama:latest

WORKDIR /app

ENV OLLAMA_HOST=0.0.0.0:5003
ENV OLLAMA_MODELS=/root/.ollama/models

RUN mkdir -p /root/.ollama/models

EXPOSE 5003

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

### entrypoint.sh
```bash
#!/bin/bash
ollama serve &
sleep 5
ollama pull llava:7b
echo "VLM OCR service ready!"
wait
```

---

## UI Mockup

```
┌─────────────────────────────────────────────────────────────────┐
│  BEn App    [CuReI]  [CuReD]  [Dictionary OCR] ←─ BETA badge   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌───────────────────────┐  ┌─────────────────────────────────┐│
│  │                       │  │  OCR Result:                    ││
│  │  ┌─────────────────┐  │  │                                 ││
│  │  │                 │  │  │  J                              ││
│  │  │  [Drag & Drop]  │  │  │                                 ││
│  │  │   AHw / CAD     │  │  │  j'l  q e'ēlu      | jšr q ešēru││
│  │  │   Page Image    │  │  │  jd'  q edû III    | jš' q ešē'u││
│  │  │                 │  │  │  jg'  q egû V      | jšd q išdu ││
│  │  └─────────────────┘  │  │  ...                            ││
│  │                       │  │                                 ││
│  │  [Browse Files]       │  │  ja q ai I 1; -ja (PrSuff...)   ││
│  │                       │  │  ja'alu q ajjalu I; ja'aru...   ││
│  └───────────────────────┘  │                                 ││
│                             │  [Edit Mode]                    ││
│  Source: [AHw ▼]            └─────────────────────────────────┘│
│  Page:   [411    ]                                              │
│                              ┌─────────────────────────────────┐│
│  [Process with DeepSeek-OCR] │ [Copy] [Export TXT] [Save ✓]   ││
│                              └─────────────────────────────────┘│
│  Status: Ready               Processing time: 2.3s              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Training Data Collection

Every user correction builds your fine-tuning dataset:

### MongoDB Collection: `ocr_corrections`
```javascript
{
  _id: ObjectId,
  image_path: "ahw/page_411.png",
  source_type: "ahw",
  page_number: 411,
  original_ocr: "jābinu d jānibu...",
  corrected_text: "jābinu q jānibu...",  // User fixed "d" → "q"
  created_at: ISODate("2026-01-26T10:00:00Z"),
  user_id: "anonymous",  // or actual user if auth enabled
  model_version: "llava-7b"
}
```

### Export Format for Fine-tuning
```json
{
  "image": "ahw/page_411.png",
  "conversations": [
    {
      "from": "human",
      "value": "<image>\nTranscribe this AHw dictionary page."
    },
    {
      "from": "gpt",
      "value": "jābinu q jānibu.\njābiš aB neben q jjābiš..."
    }
  ]
}
```

---

## Fine-tuning Path (Phase 2)

Once you collect ~500-1000 corrections:

### Using Unsloth (Recommended)
```python
from unsloth import FastVisionModel

model, tokenizer = FastVisionModel.from_pretrained(
    "deepseek-ai/DeepSeek-OCR",
    load_in_4bit=True,  # Use 4-bit for less VRAM
)

model = FastVisionModel.get_peft_model(
    model,
    r=16,  # LoRA rank
    lora_alpha=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
)

# Train on your AHw/CAD corrections
trainer = SFTTrainer(
    model=model,
    train_dataset=ahw_dataset,
    # ...
)
trainer.train()
```

**Expected improvement**: 50-60% better accuracy on AHw/CAD based on similar fine-tuning studies.

---

## Testing Checklist

- [ ] VLM container starts and loads LLaVA model via Ollama
- [ ] Health check endpoint responds
- [ ] API returns OCR text for AHw page 411
- [ ] Two-column layout is read correctly (left column first)
- [ ] Special characters (š, ṣ, ṭ, ḫ, ā, ē, ī, ū) are recognized
- [ ] Headwords are identifiable in output
- [ ] PDF upload works (converts page to image)
- [ ] Large files handled gracefully (timeout/error message)
- [ ] UI displays results correctly
- [ ] Edit mode allows corrections
- [ ] Corrections saved to MongoDB
- [ ] Export TXT works
- [ ] Beta badge shows in navigation

---

## Future Enhancements (After Beta)

1. **Fine-tune on corrections** - Train DeepSeek-OCR on collected AHw/CAD data
2. **XML Output Mode** - Structured dictionary parsing
3. **Batch Processing** - Process entire PDF volumes
4. **Side-by-side View** - Image + text for verification
5. **Confidence highlighting** - Mark uncertain regions
6. **CAD-specific model** - Separate fine-tuned model for CAD format

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| GPU not available | Fall back to CPU (slower) or cloud API |
| 4GB not enough | Use smaller model (moondream ~1.5GB) |
| Poor column detection | Add preprocessing (split columns manually) |
| Special chars missing | Fine-tune on corrections later |
| Slow inference | Batch requests, add caching |
| LLaVA not accurate enough | Upgrade to DeepSeek-OCR when more VRAM available |

---

## Sources

- [DeepSeek-OCR HuggingFace](https://huggingface.co/deepseek-ai/DeepSeek-OCR)
- [DeepSeek-OCR GitHub](https://github.com/deepseek-ai/DeepSeek-OCR)
- [Unsloth Fine-tuning Guide](https://docs.unsloth.ai/models/deepseek-ocr-how-to-run-and-fine-tune)
- [DeepSeek-OCR DataCamp Tutorial](https://www.datacamp.com/tutorial/deepseek-ocr-hands-on-guide)
- [DeepSeek-OCR vs Others Comparison](https://skywork.ai/blog/deepseek-ocr-vs-google-azure-abbyy-tesseract-paddleocr-comparison-2025/)
- [VLM Fine-tuning for Manchu OCR](https://arxiv.org/html/2507.06761v1)
