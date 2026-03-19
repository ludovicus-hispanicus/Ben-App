# CuReD Desktop — Deployment Guide

CuReD (Cuneiform Recognition Desktop) is a desktop application for cuneiform tablet transliteration. It consists of three parts:

- **Frontend**: Angular 12 single-page app (`app/`)
- **Backend**: Python FastAPI server (`server/`)
- **Desktop shell**: Electron wrapper (`electron/`)

The Electron shell launches both the backend and frontend, then loads the UI in a desktop window.

---

## Option A: Dev Mode (recommended for development / any OS)

This runs all three components from source. Works on **Windows, macOS, and Linux**.

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Node.js | 18+ | (tested with 18–22) |
| npm | 9+ | comes with Node |
| Python | 3.10–3.12 | 3.12 recommended |
| pip | latest | |
| Git | any | to clone the repo |

Optional:
- **Ollama** — if installed and running on `localhost:11434`, the app will detect it and enable local VLM OCR.

### Steps

```bash
# 1. Clone the repository
git clone <repo-url> BEn-app
cd BEn-app

# 2. Install Angular frontend dependencies
cd app
npm install
cd ..

# 3. Create a Python virtual environment and install backend dependencies
cd server
python -m venv venv

# Activate the venv:
#   Windows:  venv\Scripts\activate
#   macOS/Linux:  source venv/bin/activate

pip install -r requirements.txt
cd ..

# 4. Install Electron dependencies
cd electron
npm install
cd ..
```

### Running in dev mode

Open **two terminals** (or use the Electron launcher which does it for you):

**Terminal 1 — Backend:**
```bash
cd server
# Activate venv first (see above)
cd src
python -m uvicorn main:app --host 0.0.0.0 --port 5001
```
The API will be available at `http://localhost:5001`.

**Terminal 2 — Frontend:**
```bash
cd app
# Windows:
set NODE_OPTIONS=--openssl-legacy-provider && npx ng serve
# macOS/Linux:
NODE_OPTIONS=--openssl-legacy-provider npx ng serve
```
The frontend will be available at `http://localhost:4200`.

**Or, use Electron to launch both at once:**
```bash
cd electron
npm start
```
This starts the backend (Python) and frontend (Angular dev server) automatically, then opens the Electron window once both are ready.

### Environment variables (backend)

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_PORT` | `5001` | Backend server port |
| `APP_ENV` | — | Set to `prod` for production mode |
| `APP_DEBUG` | — | `True`/`False` |
| `STORAGE_PATH` | `data` (relative to `server/src`) | Where the JSON file-based DB is stored |
| `LOG_LEVEL` | `INFO` | Python logging level |

You can set these in a `.env` file inside `server/src/`.

---

## Option B: Windows Desktop Installer (.exe)

This bundles the backend as a PyInstaller executable and the frontend as static files into a standalone Electron app.

### Prerequisites

Same as dev mode, plus:
- **PyInstaller**: `pip install pyinstaller`
- **Windows OS** (the Squirrel maker produces a Windows `.exe` installer)

### Build steps

#### 1. Build the Angular frontend

```bash
cd app
set NODE_OPTIONS=--openssl-legacy-provider && npx ng build --configuration production
cd ..
```

This outputs the built files to `app/dist/uni-app/`.

#### 2. Bundle the Python backend with PyInstaller

```bash
cd server
# Activate venv first
cd src
pyinstaller --name cured-server --onedir --noconfirm main.py
cd ../..
```

This outputs the bundled executable to `server/src/dist/cured-server/`. The Electron config expects to find it at `server/dist/cured-server/`, so move or adjust paths accordingly:

```bash
# From repo root:
cp -r server/src/dist/cured-server server/dist/cured-server
```

#### 3. Build the Electron installer

```bash
cd electron
npm run make
```

This uses Electron Forge with the Squirrel maker to produce `CuReDSetup.exe` in `electron/out/make/squirrel.windows/`.

### What the packaged app does

When running as a packaged app (`app.isPackaged === true`):
- Serves the Angular frontend via a custom `cured://` protocol (no dev server needed)
- Launches the bundled `cured-server.exe` as a child process on port 5001
- Stores user data in `%APPDATA%/cured-desktop/data/`
- Shows a loading screen while services start up
- Checks for Ollama availability on `localhost:11434`

---

## Architecture Notes

### Data storage
- The backend uses a **JSON file-based database** (no MongoDB required)
- Files are stored under `STORAGE_PATH` (default: `server/src/data/`)
- Texts are sharded into per-dataset files under `db/texts_by_dataset/`
- An index file `text_index.json` provides O(1) text lookups

### Key ports
| Service | Port |
|---------|------|
| Python backend | 5001 |
| Angular dev server | 4200 |
| Ollama (optional) | 11434 |

### Frontend build note
Angular 12 with Node 18+ requires the `--openssl-legacy-provider` flag due to webpack 4 / OpenSSL 3 incompatibility. This is already configured in `app/package.json` scripts.

---

## Troubleshooting

- **`ERR_OSSL_EVP_UNSUPPORTED`**: Set `NODE_OPTIONS=--openssl-legacy-provider` before running Angular commands.
- **Backend won't start**: Make sure the venv is activated and all requirements are installed. Check that port 5001 is not in use.
- **Electron shows loading screen forever**: Check the terminal output for backend/frontend errors. Both services must be reachable before the app loads.
- **PyInstaller bundle fails**: Some dependencies (kraken, torch, ultralytics) may need `--hidden-import` flags. Check PyInstaller warnings.
