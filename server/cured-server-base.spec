# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the BEn API-only BASE backend.

This build ships the minimal server that powers CuReD via cloud OCR APIs
(Claude / Gemini / GPT / Grok) plus curation, lemmatization, library,
production and eBL. The heavy local-ML stack (torch / kraken / ultralytics /
CuRe classifier / local VLM) is intentionally EXCLUDED so the installer stays
small; those ship later as downloadable modules.

Build:  pyinstaller cured-server-base.spec --noconfirm
"""

import os

src_dir = os.path.join(os.getcwd(), 'src')

a = Analysis(
    [os.path.join(src_dir, 'run_server.py')],
    pathex=[src_dir],
    binaries=[],
    datas=[
        # Grammar files (Lark parser)
        (os.path.join(src_dir, 'ebl_atf_grammar'), 'ebl_atf_grammar'),
        # XML schemas
        (os.path.join(src_dir, 'schemas'), 'schemas'),
        # Prompt templates
        (os.path.join(src_dir, 'prompts'), 'prompts'),
        # Config files
        (os.path.join(src_dir, 'ebl_config.json'), '.'),
        # CSV data
        (os.path.join(src_dir, 'data', 'museums.csv'), 'data'),
        # NOTE: 'cured_models' (Kraken weights) intentionally omitted — Kraken
        # is a downloadable module, not part of the API-only base.
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
        # Cloud OCR / LLM clients
        'google.genai',
        'google.auth',
        # Image processing (no torch in base; cv2 is needed by core storage/destitch)
        'PIL',
        'fitz',  # PyMuPDF
        'cv2',   # OpenCV — used by utils/storage_utils, image_utils, destitch (core path)
        # Cloud OCR / LLM clients
        'anthropic',
        'openai',
        'google.genai',
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
        # ── Heavy local-ML stack — downloadable modules, NOT in the base ──
        'torch',
        'torchvision',
        'ultralytics',
        'kraken',
        'sklearn',        # only used by the optional CuRe training path
        'scikit_learn',
        'scipy',
        'skimage',
        # Local VLM / training stack (already excluded in full spec)
        'transformers',
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
        # ML training frameworks — training module only
        'tensorflow',
        'lightning',
        'pytorch_lightning',
        'onnxruntime',
        # Numba/triton — torch transitively, never used directly
        'numba',
        'llvmlite',
        'triton',
        # Heavy optional deps from various hooks
        'pyarrow',
        'shapely',
        'pywt',
        'imageio',
        'cloudpickle',
        'dask',
        'matplotlib',
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
