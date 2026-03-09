import logging
import os
import time

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Set default STORAGE_PATH if not set
if not os.environ.get("STORAGE_PATH"):
    os.environ["STORAGE_PATH"] = "data"

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette import status
from starlette.responses import JSONResponse

from common.env_vars import LOG_LEVEL
from init_db import init_the_db
from api.routers import cured, about, yolo_training, production, ebl, projects, cure, pages, batch_recognition, settings
from api.routers import users, text
from utils.storage_utils import StorageUtils

origins = [
    "*",
]

app = FastAPI()

# Add CORS middleware FIRST (before routers) to ensure it handles all responses including errors
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(cured.router)
app.include_router(text.router)
app.include_router(about.router)
app.include_router(yolo_training.router)
app.include_router(production.router)
app.include_router(ebl.router)  # eBL (Electronic Babylonian Literature) Integration
app.include_router(projects.router)
app.include_router(cure.router)  # CuRe Sign Classifier (separate from CuReD)
app.include_router(pages.router)  # Document Library - unified image browsing
app.include_router(batch_recognition.router)  # Batch Recognition - bulk OCR processing
app.include_router(settings.router)  # Application settings


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    exc_str = f'{exc}'.replace('\n', ' ').replace('   ', ' ')
    logging.error(f"{request}: {exc_str}")
    content = {'status_code': 10422, 'message': exc_str, 'data': None}
    return JSONResponse(content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"message": f"Internal server error: {str(exc)}"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()

    # Standalone app - no auth required, use default admin user
    user_id = "admin"
    logging.debug("=============================")
    try:
        logging.debug(f">> request from ip {request.client.host}:{request.client.port} <<")
    except:
        pass

    logging.info(f"{request.method} {request.url}")
    request.state.user_id = user_id

    try:
        response = await call_next(request)
    except Exception as e:
        logging.error(f"Middleware caught exception: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"message": f"Internal server error: {str(e)}"},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )

    process_time = time.time() - start_time
    logging.info(f"Process time: {str(process_time)}")
    logging.debug("=============================")
    return response


@app.on_event("startup")
def startup_event():
    print("startup event...")

    # Create data folder if it doesn't exist
    os.makedirs(StorageUtils.BASE_PATH, exist_ok=True)

    debug_handler = logging.FileHandler(os.path.join(StorageUtils.BASE_PATH, 'myapplog.debug'), mode='w',
                                        encoding="utf-8")
    debug_handler.setLevel(logging.DEBUG)

    info_handler = logging.FileHandler(f"{os.path.join(StorageUtils.BASE_PATH, 'myapp.log')}", encoding="utf-8")
    info_handler.setLevel(logging.INFO)

    log_level_str = os.environ.get(LOG_LEVEL, "INFO")
    log_level = logging.getLevelName(log_level_str)
    # If getLevelName returns a string (invalid level), default to INFO
    if isinstance(log_level, str):
        log_level = logging.INFO
    logging.basicConfig(format='%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s',
                        datefmt='%d/%m/%Y %H:%M:%S',
                        level=log_level,
                        force=True,  # Override any existing logging config
                        handlers=[
                            logging.StreamHandler(),
                            info_handler,
                            debug_handler
                        ])
    init_the_db()

    from common.app_settings import init_settings
    init_settings()

    # Pre-load Nemotron local model if enabled (avoids ~30s delay on first OCR request)
    if os.environ.get("PRELOAD_NEMOTRON", "false").lower() == "true":
        try:
            from clients.ocr_factory import preload_nemotron_local
            preload_nemotron_local()
        except Exception as e:
            logging.warning(f"Could not preload Nemotron model: {e}")


if __name__ == '__main__':
    port = int(os.environ.get("APP_PORT", 5001))
    uvicorn.run(app, host="0.0.0.0", port=port)
