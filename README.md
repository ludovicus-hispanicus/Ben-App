# BEn — Babylonian Engine

An AI platform for cuneiform analysis and Assyriological text curation. BEn combines
OCR/HTR, transliteration, lemmatization, and dictionary curation into a single desktop
application backed by a local database, with pluggable cloud and local recognition models.

---

## Repository layout

| Path | Stack | Purpose |
|------|-------|---------|
| `app/` | Angular 12 | Frontend UI (CuReD, Library, Production, Batch Recognition, Settings) |
| `server/` | Python + FastAPI | OCR/HTR, lemmatization, curation logic, JSON file database |
| `electron/` | Electron Forge | Desktop wrapper that bundles the frontend and Python server |
| `docs/`, `dev-instructions/` | — | Deployment notes, roadmap, architecture references |

## Main modules

- **CuReD** (Cuneiform Recognition Desktop) — the primary transliteration and curation tool.
- **CuRe** — cuneiform sign classifier.
- **Library** — dataset and text browser.
- **Production / Lemmatization** — ATF tokenization and AI-assisted lemmatization workflow.
- **Batch Recognition** — bulk OCR across datasets using cloud batch APIs.
- **Settings** — model configuration, API keys, and on-demand module installation.

## OCR / recognition architecture

BEn follows a four-tier recognition strategy (see [dev-instructions/ROADMAP.md](dev-instructions/ROADMAP.md)):

| Tier | Model | Hardware | Notes |
|------|-------|----------|-------|
| Manual Import | External (paste) | None | Bring your own OCR from any source |
| Fallback | Kraken | CPU | Offline, always available |
| Local GPU | Qwen3-VL / Nemotron + YOLO | 6–8 GB GPU | Higher quality, trainable (LoRA) |
| Premium | Cloud APIs (Claude, Gemini, GPT, Grok) | Cloud | Best quality; batch APIs supported |

Cloud provider clients live in `server/src/clients/` (`anthropic_client.py`, `grok_client.py`, …),
with batch-API support under `server/src/clients/batch_api/`.

## Data layer

- JSON file-based database via `LocalCollection` / `ShardedCollection` (`server/src/mongo/local_db_client.py`).
- Texts are sharded per dataset under `server/src/data/db/texts_by_dataset/`.
- `text_index.json` gives O(1) `text_id → dataset_id` lookup; `dataset_stats.json` holds precomputed per-dataset counts.

---

## Development

### Prerequisites

- Node.js (tested with Node 22)
- Python 3.10+
- (Optional) A CUDA-capable GPU for local VLM models

### Frontend (`app/`)

> The Angular 12 build requires the legacy OpenSSL provider on modern Node.

```bash
cd app
npm install
NODE_OPTIONS=--openssl-legacy-provider npm start   # dev server on http://localhost:4200
NODE_OPTIONS=--openssl-legacy-provider npm run build
```

The `start`/`build`/`watch`/`test` scripts already set `NODE_OPTIONS` on Windows.

### Backend (`server/`)

```bash
cd server
pip install -r requirements.txt
python src/run_server.py            # FastAPI server (entry: src/main.py)
python src/init_db.py               # initialize the local database (first run)
```

### Desktop app (`electron/`)

```bash
cd electron
npm install
npm start                           # run the packaged app locally
npm run make                        # build a distributable
```

To build the full Windows installer (`BEnSetup.exe`), use the top-level script:

```powershell
./build-desktop.ps1
```

The installer ships CuReD + Library + Settings as core modules; other modules are installed
on demand from Settings via GitHub releases.

---

## License

See individual package manifests. Authored by DigPasts.
