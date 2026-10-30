# BEn — Babylonian Engine

An AI platform for cuneiform analysis and Assyriological text curation. BEn combines
OCR/HTR, transliteration, lemmatization, and dictionary curation into a single desktop
application backed by a local database, with pluggable cloud and local recognition models.

> **About this release.** BEn is a free tool for academic, non-profit use. The installer
> provides a **basic version**: **CuReD** (OCR of transliterations in print editions, with
> layout detection, Kraken, local models via Ollama and cloud APIs, plus correction, export and
> eBL integration) and the **Library**. All of it runs on an ordinary computer without a
> graphics card.
>
> Every project is different. For anything beyond the basic version (GPU training, other
> models, your own workflows), we recommend that you **clone or fork this repository** and
> adapt the app to your project. The code is modular: each tool lives in its own folder on the
> frontend (`app/src/app/components/`) and the backend (`server/src/`). Please share
> improvements back via pull request if they may help others.

## What the basic version does

| | |
|---|---|
| **OCR with Kraken** | Fast line recognition on the CPU, offline. Ships with a model for CUSAS-style transliterations; train your own from corrected pages (CPU, no graphics card needed). |
| **Layout detection** | Finds the regions of a page (entries, headers, page numbers, …) so you can send one region to OCR with a click instead of drawing a box. Train layout models (YOLO26) on your own editions. |
| **Ollama** | Use any vision model you run locally with [Ollama](https://ollama.com). BEn lists the installed models that can read images, Ollama's cloud models, and models to download, with their size. |
| **Cloud APIs** | Gemini, Claude, OpenAI and Grok with your own API key, single pages or large batches (including the providers' cheaper batch APIs). |
| **Correction & export** | Line-by-line correction next to the image, curation for training, lemmatization, ATF export and eBL upload. |
| **Library** | Books, PDFs and page images, organised in projects. |

**Optional modules** (not in the installer, available when running from source): CuRe (sign
classifier), line segmentation, and local Qwen3-VL training and inference (needs a GPU).
Settings shows which modules are installed.

**Training on the CPU.** Training works without a graphics card, but it is slow. Layout
training with YOLO26 Nano takes about 90 seconds per epoch for 70–80 pages on a laptop CPU (a
typical run of 100 epochs: about 2.5 hours, often less with early stopping). Kraken training is
much slower: one epoch over 300 lines took about 20 minutes on a laptop CPU, so a dataset of
a few thousand lines needs hours per epoch. Even an entry-level GPU changes this: on a laptop
GPU with 8 GB (RTX 2000 Ada), fine-tuning a Kraken model on CUSAS 18 took about 2.5 minutes
for two epochs. For real training runs, use a GPU (when running from source).

## Choosing an approach

Every project has to decide how to digitise its material, depending on its budget (API costs
per page, or one-off training), its time, the people available for correction (curated lines
are what makes a local model good) and its computing power (an ordinary laptop, a GPU on
campus, or the large companies' cloud models). BEn makes these options concrete and comparable
on your own pages: a Kraken model trained locally, a model trained on a campus GPU, local vision
models through Ollama, or the cloud APIs, all with the same correction workflow. As open-source
software it can be adapted freely to a project's needs.

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
  Batch recognition, training, layout detection, production and eBL are parts of CuReD.
- **Optional modules** — CuRe, Segmentation and Qwen (local VLM) — can be enabled/disabled
  per install. A module counts as installed when its code and libraries are present
  (`server/src/common/module_status.py`, `GET /settings/modules/installed`); the navigation,
  routes and menus show only installed, enabled modules.
- Each tool is a self-contained Angular feature module (`*.module.ts`), and the navigation
  bar shows only the modules that are enabled.

How it works:

- A module registry (`APP_MODULES` in [app/src/app/services/module.service.ts](app/src/app/services/module.service.ts))
  declares each module's `id`, display name, icon and whether it is `core`.
- Enabled/disabled state is persisted server-side via `GET`/`PUT /settings/modules`
  (see [server/src/api/routers/settings.py](server/src/api/routers/settings.py)); the nav bar and
  routes are gated on that state.
- The desktop installer ships a minimal core (CuReD + Library + Settings). Additional modules are
  intended to be installed on demand from Settings, fetched from GitHub releases — the module
  model already distinguishes installed vs. not-yet-installed modules to support this.

### Main modules

- **CuReD** (Cuneiform Recognition Desktop) — the primary transliteration and curation tool,
  including batch recognition, Kraken training, layout detection and training (YOLO), production,
  lemmatization and eBL export. *(core)*
- **Library** — books, PDFs and page images; storage backbone for other modules. *(core)*
- **CuRe** — cuneiform sign classifier. *(optional)*
- **Segmentation** — line segmentation annotation tool. *(optional)*
- **Qwen** — local Qwen3-VL LoRA training and OCR on your own GPU. *(optional)*
- **Settings** — model configuration, API keys, the module manager and dashboard news.

## OCR / recognition architecture

BEn follows a four-tier recognition strategy (see [dev-instructions/ROADMAP.md](dev-instructions/ROADMAP.md)):

| Tier | Model | Hardware | Notes |
|------|-------|----------|-------|
| Manual Import | External (paste) | None | Bring your own OCR from any source |
| Local | Kraken 7 (+ YOLO layout) | CPU | Offline, always available, trainable |
| Local VLM | Any Ollama vision model; Qwen3-VL LoRA (optional module) | CPU or GPU | Markdown output; found automatically |
| Premium | Cloud APIs (Claude, Gemini, GPT, Grok) | Cloud | Best quality; live model lists; batch APIs supported |

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
cd src
python run_server.py                # FastAPI server on port 5001 (entry: main.py)
```

Start the server from `server/src`: the data folder (`STORAGE_PATH`, default `data`) is
relative to the working directory.

### Desktop app (`electron/`)

```bash
cd electron
npm install
npm start                           # run the packaged app locally
npm run make                        # build a distributable
```

To build the Windows installer (`BEnSetup.exe`) of the basic version, use the top-level script:

```powershell
./build-desktop.ps1
```

It builds the server with `server/cured-server-base.spec` into `server/dist-base` (which
Electron packages). The build environment needs the server requirements, PyInstaller and the
**CPU** build of torch (a CUDA torch adds about 3 GB and exceeds GitHub's 2 GB release-file
limit); by default the script uses the conda environment `ben-base` (`-PythonExe` to change it).
In the installed app, Kraken training runs through the server executable itself
(`cured-server --ketos …`), so no separate Python is needed.

---

## License

BEn is free software for academic, non-profit use, released under the
[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). Authored by DigPasts.

BEn bundles third-party components under their own licences, among them
[Kraken](https://github.com/mittagessen/kraken) (Apache-2.0) and
[Ultralytics YOLO](https://github.com/ultralytics/ultralytics) (AGPL-3.0).
