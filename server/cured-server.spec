# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for CuReD backend server."""

import os
import sys

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
        # Kraken OCR models
        (os.path.join(src_dir, 'cured_models'), 'cured_models'),
        # Config files
        (os.path.join(src_dir, 'ebl_config.json'), '.'),
        # CSV data
        (os.path.join(src_dir, 'data', 'museums.csv'), 'data'),
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
        # Image processing
        'cv2',
        'PIL',
        'fitz',  # PyMuPDF
        # ML frameworks
        'torch',
        'torchvision',
        'torchvision.models',
        'ultralytics',
        'kraken',
        'kraken.lib',
        'kraken.lib.train',
        'kraken.lib.models',
        'kraken.lib.dataset',
        'kraken.lib.vgsl',
        'kraken.lib.codec',
        'kraken.lib.segmentation',
        'sklearn',
        'sklearn.preprocessing',
        # Parsers
        'lark',
        'lxml',
        'lxml.etree',
        # Misc
        'aiofiles',
        'httpx',
        'dotenv',
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
        # Exclude heavy optional deps that are only for cloud/local VLM
        # Uncomment these to create a smaller build without local VLM support:
        # 'transformers',
        # 'bitsandbytes',
        # 'accelerate',
        # 'open_clip_torch',
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
