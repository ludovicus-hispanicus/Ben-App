# CuReD Desktop App — Deployment Guide

This document explains how the CuReD (Cuneiform Recognition Desktop) application works, what it needs, and how to build and distribute it as a standalone Windows `.exe`.

## Architecture Overview

CuReD is a three-tier desktop application:

```
┌─────────────────────────────────────────────────┐
│  Electron Shell (electron/)                     │
│  ┌───────────────────┐  ┌────────────────────┐  │
│  │ Angular Frontend  │  │ Python Backend     │  │
│  │ (app/)            │  │ (server/src/)      │  │
│  │                   │  │                    │  │
│  │ - UI/UX           │──│ - REST API         │  │
│  │ - Canvas editor   │  │ - OCR (Kraken/VLM) │  │
│  │ - Text management │  │ - YOLO detection   │  │
│  │                   │  │ - JSON file DB     │  │
│  └───────────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────┘
```

- **Electron** (`electron/`) — Desktop wrapper. Launches the Python backend and serves the Angular frontend. In dev mode it runs `ng serve` + `python uvicorn`; in packaged mode it serves pre-built Angular files via a custom `cured://` protocol and launches a bundled PyInstaller executable.
- **Angular Frontend** (`app/`) — Angular 12 SPA with Material Design, Fabric.js canvas, Ace editor. Communicates with the backend via REST API.
- **Python Backend** (`server/src/`) — FastAPI server providing OCR, image processing, dataset management, and training APIs. Uses a JSON file-based database (no MongoDB required for desktop).

## Prerequisites

### Required

| Tool | Version | Notes |
|------|---------|-------|
| **Node.js** | 18+ (22 tested) | Needs `NODE_OPTIONS=--openssl-legacy-provider` flag for Angular 12 |
| **npm** | 8+ | Comes with Node.js |
| **Python** | 3.10+ (3.12 tested) | With pip |
| **Git** | Any recent | To clone the repo |

### Required for Building the Desktop Installer

| Tool | Purpose |
|------|---------|
| **PyInstaller** | `pip install pyinstaller` — bundles Python + dependencies into standalone exe |
| **Electron Forge** | Already in `electron/package.json` devDependencies |

### Optional External Services

| Service | Purpose | Required? |
|---------|---------|-----------|
| **Ollama** (`localhost:11434`) | Local VLM OCR via models like LLaVA | No — falls back to Kraken OCR |
| **NVIDIA API** | Cloud Nemotron VLM OCR | No — needs `NVIDIA_API_KEY` |
| **Anthropic API** | Claude-based VLM OCR | No — needs `ANTHROPIC_API_KEY` |
| **Google GenAI API** | Gemini-based VLM OCR | No — needs `GOOGLE_GENAI_API_KEY` |
| **OpenAI API** | GPT-4 Vision OCR | No — needs `OPENAI_API_KEY` |
| **vLLM server** | Self-hosted VLM inference | No — needs `VLLM_BASE_URL` |

The app works fully offline with Kraken OCR (bundled models). VLM providers are optional enhancements.

## Project Structure

```
BEn-app/
├── app/                          # Angular 12 frontend
│   ├── src/
│   │   ├── app/components/       # UI components
│   │   │   ├── cure-d/           # Main transliteration tool
│   │   │   ├── cure/             # Sign classifier
│   │   │   └── ...
│   │   ├── environments/
│   │   │   ├── environment.ts          # Dev (localhost:5002)
│   │   │   ├── environment.prod.ts     # Production (relative /api/v1)
│   │   │   └── environment.desktop.ts  # Desktop (localhost:5001)
│   │   └── ...
│   ├── angular.json              # Build configs: production, desktop, development
│   └── package.json
│
├── server/                       # Python FastAPI backend
│   ├── src/
│   │   ├── main.py               # FastAPI app entry point
│   │   ├── run_server.py         # PyInstaller entry point
│   │   ├── api/routers/          # REST API endpoints
│   │   ├── clients/              # OCR/VLM client adapters
│   │   │   ├── kraken_client.py  # Local Kraken OCR
│   │   │   ├── anthropic_client.py
│   │   │   ├── gemini_client.py
│   │   │   ├── nemotron_client.py
│   │   │   ├── ollama_client.py
│   │   │   ├── openai_client.py
│   │   │   ├── vllm_client.py
│   │   │   └── ocr_factory.py   # Client registry/factory
│   │   ├── mongo/
│   │   │   └── local_db_client.py  # JSON file-based DB
│   │   ├── cured_models/         # Bundled Kraken .mlmodel files
│   │   ├── ebl_atf_grammar/      # Lark grammar files for ATF parsing
│   │   ├── schemas/              # XSD schemas for TEI validation
│   │   ├── prompts/              # VLM prompt templates
│   │   └── data/
│   │       └── museums.csv       # Museum reference data
│   ├── requirements.txt
│   └── cured-server.spec         # PyInstaller build spec
│
├── electron/                     # Electron desktop wrapper
│   ├── main.js                   # App lifecycle, process management
│   ├── preload.js                # IPC bridge
│   ├── loading.html              # Splash screen
│   ├── assets/                   # App icons
│   └── package.json              # Electron Forge config
│
├── build-desktop.ps1             # Build orchestration script
└── dev-instructions/             # This folder
```

## Environment Variables

The Python backend uses these environment variables (all optional for desktop use):

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_PORT` | `5001` | Backend server port |
| `STORAGE_PATH` | `data` (relative) | Base path for all data storage. In desktop mode, Electron sets this to the user's app data folder |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `ANTHROPIC_API_KEY` | — | For Claude OCR |
| `GOOGLE_GENAI_API_KEY` | — | For Gemini OCR |
| `NVIDIA_API_KEY` | — | For Nemotron cloud OCR |
| `OPENAI_API_KEY` | — | For GPT-4 Vision OCR |
| `VLLM_BASE_URL` | `http://localhost:8000/v1` | For self-hosted vLLM |
| `VLLM_MODEL_NAME` | `Qwen/Qwen3-VL-8B-Instruct` | Model name for vLLM |
| `PRELOAD_NEMOTRON` | `false` | Preload local Nemotron model on startup |

## Data Storage

The app uses a JSON file-based database (no MongoDB needed):

```
{STORAGE_PATH}/
├── db/                           # Database files
│   ├── texts.json / texts_by_dataset/  # Text documents (sharded)
│   ├── datasets.json             # Dataset metadata
│   ├── projects.json             # Project metadata
│   ├── users.json                # User accounts
│   ├── text_index.json           # text_id → dataset_id lookup
│   ├── dataset_stats.json        # Precomputed counts
│   └── ...
├── images/                       # Original text images
├── user_upload/                  # User-uploaded images
├── preview/                      # Thumbnail cache (250×250 JPEG)
├── cured_training_data/          # Training datasets
├── production_images/            # Production uploads
├── myapp.log                     # Application log
└── myapplog.debug                # Debug log
```

## Ports

| Service | Port | Configurable via |
|---------|------|------------------|
| Python backend | 5001 | `APP_PORT` env var |
| Angular dev server | 4200 | Only used in dev mode |
| Ollama | 11434 | External service |

## Development Setup

### 1. Install dependencies

```bash
# Frontend
cd app
npm install

# Backend
cd server
pip install -r requirements.txt

# Electron
cd electron
npm install
```

### 2. Run in dev mode

Option A — Run each service separately:
```bash
# Terminal 1: Backend
cd server/src
python -m uvicorn main:app --host 0.0.0.0 --port 5001

# Terminal 2: Frontend
cd app
NODE_OPTIONS=--openssl-legacy-provider npx ng serve

# Terminal 3: Electron (optional — wraps the above)
cd electron
npm start
```

Option B — Run via Electron (starts both automatically):
```bash
cd electron
npm start
```

## Building the Desktop Installer

### Quick build (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File build-desktop.ps1
```

Flags:
- `-SkipAngular` — Skip Angular build (reuse existing dist)
- `-SkipPython` — Skip PyInstaller build (reuse existing dist)
- `-PackageOnly` — Create portable folder instead of installer

### Manual step-by-step

#### Step 1: Build Angular frontend

```bash
cd app
NODE_OPTIONS=--openssl-legacy-provider npx ng build --configuration=desktop
```

Output: `app/dist/uni-app/` (static HTML/JS/CSS files)

The `desktop` configuration:
- Uses `environment.desktop.ts` (API URL = `http://localhost:5001/api/v1`)
- Sets `baseHref: "./"` for file-based loading
- Disables output hashing for cleaner filenames

#### Step 2: Bundle Python backend

```bash
cd server
pip install pyinstaller
pyinstaller cured-server.spec --noconfirm
```

Output: `server/dist/cured-server/` containing `cured-server.exe` and all dependencies.

**Size reduction tip:** Install CPU-only PyTorch before building to save ~1.5GB:
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

**Troubleshooting:** If the built exe crashes with `ModuleNotFoundError`, add the missing module to the `hiddenimports` list in `cured-server.spec` and rebuild.

#### Step 3: Package Electron

```bash
cd electron
npm run make
```

Output: `electron/out/make/squirrel.windows/x64/CuReDSetup.exe`

This step:
1. Copies `app/dist/uni-app/` and `server/dist/cured-server/` into the app's `resources/` folder (via `extraResource` in forge config)
2. Creates a Squirrel installer for Windows

### What the packaged app looks like

```
CuReD-win32-x64/
├── cured-desktop.exe              # Main Electron executable
└── resources/
    ├── app/                       # Electron app code (main.js, preload.js, etc.)
    ├── uni-app/                   # Angular dist (served via cured:// protocol)
    │   ├── index.html
    │   ├── *.js, *.css
    │   └── assets/
    └── cured-server/              # PyInstaller output
        ├── cured-server.exe       # Python backend executable
        └── _internal/             # Bundled Python runtime + packages
```

### How the packaged app runs

1. User launches `cured-desktop.exe`
2. Electron shows a loading splash screen
3. Electron spawns `cured-server.exe` from `resources/cured-server/`
4. Electron registers a custom `cured://` protocol to serve Angular files from `resources/uni-app/`
5. Electron polls `http://localhost:5001` until the backend is ready
6. Electron loads `cured://app/index.html` in the main window
7. The Angular app communicates with the Python backend via `http://localhost:5001/api/v1`
8. On quit, Electron kills the Python process tree

User data is stored in: `%APPDATA%/cured-desktop/data/`

## Key Technical Details for AI Agents

### Angular build quirks
- Angular 12 requires `NODE_OPTIONS=--openssl-legacy-provider` with Node 18+
- The project name in `angular.json` is `uni-app`, so output goes to `dist/uni-app/`

### Python backend architecture
- Entry point: `server/src/main.py` (FastAPI app)
- PyInstaller entry: `server/src/run_server.py` (sets cwd, imports main, runs uvicorn)
- No authentication — hardcoded `user_id = "admin"` in middleware
- CORS is fully open (`allow_origins=["*"]`)
- Database: JSON files via `LocalDBClient` and `ShardedCollection` in `mongo/local_db_client.py`
- `STORAGE_PATH` env var controls where all data lives. `LocalDBClient.STORAGE_DIR` derives from it.

### Electron dual-mode behavior
- `app.isPackaged` determines dev vs production mode
- Dev: spawns `python -m uvicorn` + `npm start` (ng serve)
- Packaged: spawns bundled `cured-server.exe` + serves Angular via `cured://` protocol
- Windows process cleanup uses `taskkill /T /F` to kill the entire process tree

### OCR pipeline
- Default: **Kraken OCR** (bundled `.mlmodel` files in `server/src/cured_models/`)
- Optional: VLM-based OCR via cloud APIs (Anthropic, Google, NVIDIA, OpenAI) or local services (Ollama, vLLM)
- Client selection: `server/src/clients/ocr_factory.py`
- All VLM clients send a base64-encoded image + prompt and receive transliteration text back

### PyInstaller bundled resources
The spec file (`server/cured-server.spec`) bundles these non-Python files:
- `ebl_atf_grammar/*.lark` — ATF parser grammar
- `schemas/*.xsd` — TEI XML validation schemas
- `prompts/tei_lex0/` — VLM prompt templates + examples
- `cured_models/` — Kraken OCR models
- `ebl_config.json` — eBL API config
- `data/museums.csv` — Museum reference data

### Known issues
- **Large build size** (~3-5GB) due to PyTorch, ultralytics, kraken, transformers. Use CPU-only PyTorch to reduce.
- **Antivirus false positives** — PyInstaller executables are commonly flagged. Code signing recommended.
- **PyInstaller hidden imports** — May need tuning. If the exe crashes with `ModuleNotFoundError`, add the module to `hiddenimports` in the spec file.
- **Windows-only tested** — The build script is PowerShell. macOS/Linux would need a bash equivalent and different PyInstaller output.
