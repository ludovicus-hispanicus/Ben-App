# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the BEn BASE backend: CuReD + Library.

The base ships what CuReD needs on a normal computer (CPU only):
  * Kraken 7.1 OCR and training (CPU torch; ``cured-server --ketos`` runs ketos,
    see run_server.py), with the bundled Kraken models
  * layout detection and training (Ultralytics YOLO26 / YOLOv8)
  * Ollama and the cloud OCR APIs (Claude / Gemini / GPT / Grok)
  * curation, lemmatization, Library, production and eBL

Left out (optional modules, reported as "not installed" by
common/module_status.py, which checks for their code):
  * CuRe sign classifier, line segmentation, local Qwen3-VL (LoRA)
  * the local VLM stack (transformers, peft, bitsandbytes, ...)

Build it in an environment with **CPU** torch (a CUDA torch adds ~3 GB of DLLs
and breaks GitHub's 2 GB per-file release limit):

    pyinstaller cured-server-base.spec --noconfirm --distpath dist-base --workpath build-base

Electron packages ``server/dist-base/cured-server`` (electron/package.json).
"""

import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

src_dir = os.path.join(os.getcwd(), 'src')

# Kraken models shipped with the app: the model files and the registry/active
# model, not training scratch folders (_train_*) left in cured_models/.
kraken_models = [
    (path, 'cured_models')
    for pattern in ('*.safetensors', '*.mlmodel', 'active_model.txt', 'registry.json')
    for path in glob.glob(os.path.join(src_dir, 'cured_models', pattern))
]

a = Analysis(
    [os.path.join(src_dir, 'run_server.py')],
    pathex=[src_dir],
    binaries=[],
    datas=[
        # Kraken 7 finds its model/loader/trainer classes through entry points in
        # the package metadata; without the dist-info: "No loader found".
        *copy_metadata('kraken'),
        *copy_metadata('lightning'),
        *copy_metadata('pytorch_lightning'),
        *collect_data_files('kraken'),
        # Ultralytics reads its model/config YAML files at runtime
        *collect_data_files('ultralytics'),
        # Grammar files (Lark parser)
        (os.path.join(src_dir, 'ebl_atf_grammar'), 'ebl_atf_grammar'),
        # XML schemas
        (os.path.join(src_dir, 'schemas'), 'schemas'),
        # Prompt templates
        (os.path.join(src_dir, 'prompts'), 'prompts'),
        # CSV data
        (os.path.join(src_dir, 'data', 'museums.csv'), 'data'),
        # Kraken OCR models
        *kraken_models,
        # NOT ebl_config.json: it holds the eBL login of whoever builds the app.
        # Without it BEn starts logged out of eBL and creates its own on login.
    ],
    hiddenimports=[
        # FastAPI / Uvicorn
        'uvicorn.logging',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'fastapi',
        'pydantic',
        'starlette',
        'multipart',
        'python_multipart',
        # Database
        'pymongo',
        'bson',
        'bson.objectid',
        'dns',  # pymongo srv resolver
        # Auth / crypto
        'jwt',
        'OpenSSL',
        # Git-backed storage
        'pygit2',
        'pgzip',
        # Image processing
        'PIL',
        'fitz',  # PyMuPDF
        'cv2',
        # ML: CPU torch, Kraken 7.x, Ultralytics
        'torch',
        'torchvision',
        'ultralytics',
        # Kraken 7.x resolves model classes, loaders, trainers and ketos
        # subcommands through importlib.metadata entry points (kraken.models /
        # kraken.loaders / kraken.lightning_modules / kraken.configs), so every
        # submodule must be bundled (and the metadata copied, see datas).
        *collect_submodules('kraken'),
        'lightning',
        'lightning.pytorch',
        'lightning.fabric',
        'pytorch_lightning',
        'safetensors',
        'safetensors.torch',
        'coremltools',   # legacy .mlmodel loader (kraken <= 6 models)
        'torchmetrics',
        'threadpoolctl',
        'htrmopo',
        'yaml',          # ketos --config experiment files
        'services.ketos_wrapper',  # cured-server --ketos (Kraken training)
        # Cloud OCR / LLM clients
        'anthropic',
        'openai',
        'google.genai',
        'google.auth',
        'httpx',
        # Parsers
        'lark',
        'lxml',
        'lxml.etree',
        # Misc
        'aiofiles',
        'dotenv',
        'email_validator',  # lazy-imported by pydantic for EmailStr
        'encodings',
        'encodings.utf_8',
        'encodings.ascii',
        'encodings.latin_1',
        'numpy',
        'pandas',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ── Optional modules: their code stays out, so BEn reports them as
        # "not installed" (common/module_status.py checks for it) ──
        'api.routers.cure',
        'api.routers.segmentation',
        'services.qwen_training_service',
        'services.qwen_ocr_service',
        'services.qwen3_vl_service',
        'clients.qwen_lora_client',
        # Local VLM / training stack (Qwen LoRA etc.)
        'transformers',
        'peft',
        'bitsandbytes',
        'accelerate',
        'open_clip_torch',
        'datasets',
        'unsloth',
        'unsloth_zoo',
        'xformers',
        # NLP — pulled in by hooks but never imported by src/
        'spacy',
        'thinc',
        'blis',
        # Other ML frameworks
        'tensorflow',
        'onnxruntime',
        'triton',
        # Numba / LLVM (~100 MB): pulled in by hooks, not used by Kraken or Ultralytics here
        'numba',
        'llvmlite',
        # Heavy optional deps from various hooks
        'dask',
        'IPython',
        'jupyter',
        'notebook',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cured-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Keep console for logging
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='cured-server',
)
