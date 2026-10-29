# BEn base release — scope and assessment

Status: draft, 2026-10-29. Based on a code audit of `main` plus the uncommitted Kraken 7.1 upgrade.

## 1. Target scope

BEn is a free tool for academic, non-profit use. The base release covers:

CuReD is built for **transliterations in academic publications** (print editions, dictionaries such as AHw), not for cuneiform signs. Layout detection serves that same workflow, so it lives inside CuReD rather than as a separate module.

| Area | Base (always installed) | Optional download |
|---|---|---|
| **CuReD** — OCR and curation | Kraken OCR + Kraken training on **CPU** | Kraken training on **GPU** |
| | Ollama: any vision model the user has pulled, chosen by the user (no fixed list) | |
| | Cloud APIs (Gemini, Claude, OpenAI, Grok, NVIDIA): live model lists, incl. Batch | |
| | **Layout detection** (newest YOLO, YOLO26): detection + training on **CPU**; detected regions can be sent straight to OCR | Layout training on **GPU** |
| | Correction workflow: editor, production/export, lemmatization | |
| | eBL integration | |
| **Library** | Dataset and image browser | |

Everything else is optional or hidden in this release (see §3).

## 2. Assessment by area

### CuReD — Kraken

- **Done (uncommitted):** upgrade to Kraken 7.1.1.
  - New default model `CUSAS-18-3` (PP-OCRv6 tiny, fine-tuned). Character error rate 6.2% vs 7.9% for `CUSAS-18-2` on 944 held-out CUSAS lines. 2.8 MB instead of 17 MB.
  - Old `.mlmodel` files keep working, and run about 3.7× faster under Kraken 7.
  - OCR and training verified in the running app, on GPU only.
- **To do:**
  - **CPU training speed has not been measured.** Measure a fine-tune of `CUSAS-18-3` on ~1,600 lines on CPU before promising CPU training. If it takes hours, the UI should say so and suggest small datasets.
  - **Ship the PP-OCRv6 tiny base model** (Apache-2.0, 2.8 MB). New datasets should fine-tune from it; today, training without a base starts from random weights.
  - **Fix training scoped to a single dataset.** It reports 0 curated lines. This bug predates the upgrade.
  - **Fix the line minimum for the default training option.** "Active model" fine-tunes the active model but still requires the 500-line minimum meant for training from scratch.

### CuReD — Ollama

- **Today:**
  - The backend reads the installed models from Ollama (`/api/tags`), but filters them by a fixed list of name fragments (`llava`, `qwen`, …), in `api/routers/cured.py:147-161`.
  - The CuReD UI shows a fixed list of model names (`clients/ollama_client.py:19`, `cured.component.ts` "Local GPU" category) and only marks which of them are installed.
- **To do:**
  - **Detect vision models by capability, not by name.** Ollama's `/api/show` reports a `vision` capability per model.
  - **Show every installed vision model in CuReD,** plus a free-text field for a model name.
  - **Keep recommended models as suggestions only.** The current list becomes "suggested models to pull" with the `ollama pull` command, not the set of selectable models.

### CuReD — cloud APIs

- **Today:** CuReD hard-codes model names (`cured.component.ts:289-296`, e.g. `gemini-3.1-pro-preview`, `claude-opus-4-8`). Batch Recognition already uses the live catalog (`services/model_catalog.py`, `latest:<family>` aliases).
- **To do:**
  - **Use the same catalog in CuReD,** so model lists don't go stale between releases.
  - **Keep a short built-in fallback list** for when no API key has been entered yet.

### CuReD — layout detection (YOLO)

Purpose: avoid drawing the OCR box by hand on every page. The page is analysed in the background, the user picks a detected region, and that region goes to Kraken (or Ollama/API).

- **Today:**
  - **Layout detection is a separate page** (`/yolo-training`, "Layout"). It detects regions, extracts snippets, saves them to the Library, and Batch Recognition then OCRs them, deriving the class from the snippet filename (the AHw route).
  - **CuReD's page editor has no layout step.** Boxes are drawn by hand, or predicted as text lines by Kraken.
  - **The CuReD hub already imports `YoloTrainingModule`** and has an unused `TrainingTab.YOLO` (`components/training/training.component.ts:25-28`).
  - **Ultralytics 8.4.13 is installed,** which already includes YOLO26. BEn only offers YOLOv8 n–x as base models (`clients/yolo_training_client.py:53-57`).
  - **CPU fallback works** (`yolo_training_client.py:1225-1227`).
  - **Existing trained models are YOLOv8-based** (AHw, CAD).
- **To do:**
  - **Page editor:** on page load, run the active layout model (`POST /yolo/predict`) and draw the detected regions on the canvas. The user clicks one or more regions to send to OCR; manual drawing stays as a fallback. Make it toggleable, with a per-dataset choice of layout model.
  - **CuReD hub:** add a **Layout** tab (annotate, train, run, export snippets) next to Datasets / Models / Training / Batch / Export. It replaces the separate `/yolo-training` page in the navigation and also covers "layout only" use.
  - **Add YOLO26 n/s/m as base models,** with YOLO26n the default for CPU. Ultralytics' own benchmark: YOLO26n 38.9 ms vs YOLOv8n 80.4 ms per image on CPU (ONNX), with higher accuracy. Existing v8 models keep working; they only improve if retrained.
  - **Measure CPU training time** for YOLO26n on one of our layout datasets before advertising CPU training.

### Library

No changes needed for the base.

## 3. Module consistency — what has to change

The audit found that the backend already boots without the heavy ML libraries, because they're imported only when used. The gaps are in packaging and in the UI.

**Blockers for the release**

1. **The base installer contains no Kraken.**
   - `server/cured-server-base.spec` excludes `kraken`, `torch`, `torchvision` and `lightning`, and doesn't bundle the models. That was v1.0.0's cloud-only design.
   - For this base it must include Kraken 7.1, **CPU-only torch**, `ultralytics`, `lightning==2.6.1`, and the models from `cured_models/`.
   - Installer size has to be measured; it must stay under GitHub's 2 GB per-asset limit.
2. **The build script builds the wrong spec.** `build-desktop.ps1` builds `cured-server.spec` into `dist/`, but Electron packages `dist-base/` (`electron/package.json:40-42`).
3. **CuReD shows tools that aren't in the base:**
   - The Training tab offers Qwen and TrOCR training. Both need torch + `transformers` (and TrOCR returns HTTP 500 when they're missing), and they're mislabelled "CPU" (`cured.component.ts:436-439`).
   - The CuReD hub calls the YOLO API on every visit (`training.component.ts:261-262`). Once layout is part of CuReD this is expected, but it must not show error messages when no layout model exists yet.
4. **The app can't tell which modules are installed.**
   - `installed: true` is hard-coded (`app/src/app/services/module.service.ts:16-20`).
   - Optional routers register even when their libraries are missing (`server/src/main.py:63-86`).
   - The backend should report which optional libraries can be imported (extend `GET /settings/modules`), and Settings should show "Install" for the rest.

**Should fix**

5. **Library and the dashboard link to CuRe and Layout without checking whether they're enabled.** The click then silently redirects home (`document-library.component.html:337,340`, `admin-panel.component.html:59`).
6. **Fail cleanly when a dependency is missing:**
   - `NEMOTRON_MODE=local` stops the server from starting without torch (`handlers/cured_handler.py:18-19`).
   - CuRe and TrOCR OCR return HTTP 500 instead of "module not installed".
7. **Clarify modules without an id.** Batch, Export/production, lemmatization and eBL are part of CuReD (base). Destitch's screen lives inside the Segmentation module but is core on the backend; decide which it is.
8. **Split `server/requirements.txt`** into a base list and per-module lists.
9. **Layout moves into CuReD.** Retire `yolo` as a separate optional module id (`module.service.ts`, `app_settings.py`, nav, route guard), or keep the old route as a redirect to the CuReD Layout tab.

**Not in this release's base:** CuRe, line segmentation (Kraken pageseg UI), local Qwen / TrOCR / Nemotron training and inference. Keep the code, hide the UI unless the module is installed.

## 4. Open decisions

- **GPU training (Kraken and YOLO).** The desktop app is a frozen PyInstaller bundle, so its Python can't be switched from CPU torch to CUDA torch afterwards. Options:
  - **(a) Separate "GPU pack" download:** a frozen trainer process with CUDA torch that BEn calls. It's about 3–4 GB, so it must be split across release assets or hosted on Zenodo / Hugging Face.
  - **(b) GPU training by running BEn from source** (clone + conda env), documented in the README.
  - **Recommendation:** (b) for this release, (a) later if there is demand. This matches the "make your own fork" recommendation below.
- **Licence.** Ultralytics (YOLO) is AGPL-3.0. Bundling it means BEn must be released under AGPL-3.0 (fine for a free, open academic tool; Kraken's Apache-2.0 is compatible). Add a `LICENSE` file before publishing; the repo currently has none, which legally means "all rights reserved". Check with the university's tech-transfer / legal office if required.

## 5. Suggested order of work

1. Licence decision + `LICENSE` file.
2. Commit the Kraken 7.1 upgrade.
3. Base spec with Kraken + CPU torch + Ultralytics; fix the build script; build and measure installer size; boot-test.
4. Measure CPU training time (Kraken tiny, YOLO26n).
5. UI gating: hide Qwen/TrOCR, gate YOLO calls and links, report installed modules.
6. Ollama: capability-based model discovery.
7. Cloud APIs: live model catalog in CuReD.
8. Layout inside CuReD: YOLO26 base models, Layout tab in the hub, detect-and-pick in the page editor.
9. Frontend update (§6), including the further add/remove list.
10. README: base-version notice (§7).

## 6. Frontend update

Layout no longer gets its own page, so its functions move into CuReD. At the same time CuReD gains and loses some functions. This section collects those changes.

### Current UI (inventory, 2026-10-29)

- **Top navigation:** CuReD · CuRe · Layout · Segmentation · Library · Settings · About.
- **Dashboard (`/`, "Admin Panel"):** user activity, system statistics, recent actions, model management, quick access (links to CuReD and Layout).
- **CuReD hub (`/cured`):** tabs Datasets · Models · Training · Batch · Export.
  - **Training engines:** Kraken · Qwen · TrOCR.
- **CuReD page editor:**
  - **OCR model menu:**
    - Pre-trained (Kraken models)
    - "CPU" (Kraken, Qwen LoRA, TrOCR)
    - "Local GPU" (fixed list of Ollama models + Nemotron local)
    - "Ollama Cloud" (Qwen3-VL 235B, 235B Thinking)
    - "API" (Nemotron, GPT-4 Vision, Claude, Gemini, Grok)
  - **Line boxes:** None · Estimate · Predict (Kraken).
- **Layout page (`/yolo-training`):** datasets, annotation, training, models, predict + extract snippets → Library.

### Changes already decided

- **Navigation:** remove Layout, CuRe and Segmentation from the top bar unless their module is installed. Base nav: CuReD · Library · Settings · About.
- **CuReD hub:** add a **Layout** tab: annotate, train, run, export snippets (from the Layout page).
- **CuReD page editor:**
  - **Region selection:** add "Layout (YOLO)": detect regions on page load, click a region to OCR it.
  - **Ollama:** replace the fixed list with all installed vision models + free-text model name; suggested models only as "how to pull" hints.
  - **API:** live model lists instead of hard-coded names.
  - **Remove** Qwen LoRA, TrOCR and Nemotron local from the menu (unless a local-model module is installed). Fix the "CPU" / "Local GPU" labels.
- **CuReD hub, Training tab:** Kraken only in the base (Qwen and TrOCR hidden).
- **Dashboard and Library:** remove or gate links to Layout/CuRe.

### Dashboard (new design)

The current dashboard (`components/admin-panel/`, "Admin Panel") is four "Coming Soon" placeholder cards plus two quick links. It is replaced by a single-page dashboard of cards, without tabs:

1. **Continue working:** the last 5 edited texts, opening directly in CuReD. Source: texts' last-modified dates.
2. **Start something:** large entry points for New OCR (upload a page), Library, Batch OCR, Train a model, Export, eBL.
3. **Your data:** datasets, texts, curated texts / lines, progress per dataset. Source: `data/db/dataset_stats.json`, `GET /cured/curated-stats`.
4. **Engines:** readiness of each OCR engine:
   - Kraken: active model.
   - Layout: active YOLO model.
   - Ollama: running? number of vision models installed.
   - Cloud APIs: which keys are set.

   This is the first place to look when OCR fails.
5. **Recent activity:** last training runs (Kraken, layout) and batch jobs with status. Sources: the training histories, `batch_recognition_jobs.json`.
6. **News** (English only), from a `NEWS.md` file at the repo root, edited directly on GitHub:
   - **Format:** one `## YYYY-MM-DD — Title` heading per entry, followed by Markdown text, newest first. The dashboard shows the newest 3 entries, marking those added since the user last opened BEn.
   - **When:** fetched on app start, in the background (startup never waits), at most once a day. The result is cached locally; offline, the cache is shown.
   - **Version check:** the same daily check reads the latest release tag and shows a "new version available" badge when it is newer than the installed version.
   - **Opt-out:** a switch in Settings turns the news off, since it contacts GitHub.

   ```markdown
   # BEn News

   ## 2026-11-15 — BEn 2.0 released
   Kraken 7.1 with a new CUSAS model, layout detection inside CuReD, …
   ```

Dropped: "Admin Panel" title and "User Activity" (BEn is a single-user desktop app).

Needs:
- **A small backend endpoint aggregating cards 1, 3, 4 and 5.**
- **A backend endpoint that fetches and caches the news** so the frontend never calls GitHub directly. Sources: `raw.githubusercontent.com/ludovicus-hispanicus/Ben-App/main/NEWS.md` and `api.github.com/repos/ludovicus-hispanicus/Ben-App/releases/latest` for the version check. Cache in `data/db/news_cache.json` with the fetch date.
- **A first `NEWS.md` in the repo.**

### Navigation

As a desktop app, BEn has no browser back button, so every screen needs an obvious way back.

**Problems found:**
- **Saved texts have no back button.** The ← button in the editor's side toolbar only appears for fresh uploads (`*ngIf="!isLoadedFromServer && !viewOnly"`, `cure-d/cured.component.html:654`). A text opened from a dataset has no back button at all.
- **The hub tabs vanish in the editor.** The hub hides them while the editor is open (`hideChrome`, `training/training.component.ts`), so users return by clicking "CuReD" in the top bar.
- **The shared back slot is unused.** The top bar supports a back button (`ToolbarService.backAction`), but CuReD always clears it (`cured.component.ts:1244`).
- **Back events never fire in Electron.** CuReD pushes its screens into the browser history and handles back events (`goBack(fromBrowser)`), but Electron offers no back button, and the mouse back button and Alt+← aren't wired.
- **Unsaved changes are only protected by the editor's own back button.**

**Changes:**
1. **One back button in the top bar,** labelled with its destination ("← CUSAS-18 texts", "← Production", "← Dashboard"), on every screen below the top level, including saved texts.
2. **Breadcrumb** next to it (`CuReD › CUSAS-18 › Text 4985279`), every part clickable. It replaces the hidden hub tabs while the editor is open.
3. **Back returns to the origin.** A text opened from Library, Production or the dashboard's "Continue working" card returns there. Generalise the existing "Back to production" linked mode into a `returnTo` parameter.
4. **Mouse back button, Alt+← and Esc** (when no dialog is open) trigger the same action. In Electron, handle `app-command` `browser-backward` in `electron/main.js`, and add a keyboard shortcut.
5. **One unsaved-changes check for every exit path:** back button, breadcrumb, top bar, keyboard, closing the window.

**Status (2026-10-29):** 1–5 done for CuReD (dataset list, saved texts, new OCR, linked pages).
- **Tested in the browser:** back, breadcrumb, side-toolbar back, and unsaved-changes prompts.
- **Not yet tested:** Alt+←, the mouse back button and the close-window dialog, which need the packaged desktop app.
- **Esc is not bound:** the editor already uses it for its own actions.
- **`returnTo` has no callers yet:** the dashboard's "Continue working" card will be the first.
- **Production's editor (Export tab) is not covered yet.**

### Further changes (to be specified)

- **Add:** _…_
- **Remove:** _…_

## 7. README text (draft)

> **About this release.** BEn is a free tool for academic, non-profit use. The installer
> provides a **basic version**: CuReD (OCR of transliterations in print editions, with layout
> detection, Kraken, local models via Ollama and cloud APIs, plus correction, export and eBL
> integration) and the Library. All of it runs on an ordinary computer without a graphics card.
>
> Every project is different. For anything beyond the basic version (GPU training, other
> models, your own workflows), we recommend that you **clone or fork this repository** and
> adapt the app to your project. The code is modular, and each tool lives in its own folder
> on the frontend (`app/src/app/components/`) and the backend (`server/src/`). Please share
> improvements back via pull request if they may help others.
