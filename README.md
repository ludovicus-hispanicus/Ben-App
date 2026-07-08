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

## Modular architecture

BEn is designed as a **modular app**: a small, always-present core plus optional modules
that can be turned on or off (and, going forward, installed on demand) so each user runs only
the tools they need.

- **Core modules** ship with every install and cannot be disabled: **CuReD** and **Library**
  (the storage backbone the other modules depend on). **Settings** hosts the module manager.
- **Optional modules** — CuRe, Layout (YOLO), Segmentation, Batch Recognition, Production,
  Training — can be enabled/disabled per install.
- Each tool is a self-contained Angular feature module (`*.module.ts`), and the navigation
  bar shows only the modules that are enabled.

How it works:

- A module registry (`APP_MODULES` in [app/src/app/services/module.service.ts](app/src/app/services/module.service.ts))
  declares each module's `id`, display name, icon, whether it is `core`, and whether it is `installed`.
- Enabled/disabled state is persisted server-side via `GET`/`PUT /settings/modules`
  (see [server/src/api/routers/settings.py](server/src/api/routers/settings.py)); the nav bar and
  routes are gated on that state.
- The desktop installer ships a minimal core (CuReD + Library + Settings). Additional modules are
  intended to be installed on demand from Settings, fetched from GitHub releases — the module
  model already distinguishes installed vs. not-yet-installed modules to support this.

### Main modules

- **CuReD** (Cuneiform Recognition Desktop) — the primary transliteration and curation tool. *(core)*
- **Library** — dataset and text browser; storage backbone for other modules. *(core)*
- **CuRe** — cuneiform sign classifier.
- **Layout** — YOLO layout detection & training.
- **Segmentation** — line segmentation annotation tool.
- **Production / Lemmatization** — ATF tokenization and AI-assisted lemmatization workflow.
- **Batch Recognition** — bulk OCR across datasets using cloud batch APIs.
- **Settings** — model configuration, API keys, and the module manager.

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
