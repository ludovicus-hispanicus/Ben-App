import logging
import os
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette import status
from starlette.responses import JSONResponse

from auth.auth_bearer import JWTBearer
from auth.auth_handler import decode_jwt
from common.env_vars import LOG_LEVEL
from init_db import init_the_db
from api.routers import cured, about, yolo_training
from api.routers import users, amendment, detexify, text
from utils.storage_utils import StorageUtils

# VLM OCR is optional - requires MongoDBClient and DeepSeek-OCR service
try:
    from api.routers import vlm_ocr
    vlm_ocr_available = True
except ImportError as e:
    logging.warning(f"VLM OCR router not available: {e}. Dictionary OCR features will be disabled.")
    vlm_ocr_available = False

origins = [
    "*",
]

app = FastAPI()
app.include_router(amendment.router)
app.include_router(detexify.router)
app.include_router(users.router)
app.include_router(cured.router)
app.include_router(text.router)
app.include_router(about.router)
if vlm_ocr_available:
    app.include_router(vlm_ocr.router)  # Dictionary OCR (Beta)
app.include_router(yolo_training.router)  # YOLO Layout Detection Training

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    exc_str = f'{exc}'.replace('\n', ' ').replace('   ', ' ')
    logging.error(f"{request}: {exc_str}")
    content = {'status_code': 10422, 'message': exc_str, 'data': None}
    return JSONResponse(content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


# @app.exception_handler(Exception)
# async def unicorn_exception_handler(request: Request, exc: Exception):
#     return JSONResponse(
#         status_code=500,
#         content={"message": f"Oops! something went wrong ({str(exc)})"},
#     )


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()

    user_id = None
    logging.debug("=============================")
    logging.debug(f">> request from ip {request.client.host}:{request.client.port} <<")
    try:
        user_id = decode_jwt(token=await JWTBearer().__call__(request))['user_id']
        logging.info(f"request by user: {user_id if user_id else 'Unknown user'}")
    except:
        pass

    logging.info(f"{request.method} {request.url}")
    request.state.user_id = user_id
    response = await call_next(request)
    process_time = time.time() - start_time
    logging.info(f"Process time: {str(process_time)}")
    logging.debug("=============================")
    return response


@app.on_event("startup")
def startup_event():
    print("startup event...")
    debug_handler = logging.FileHandler(os.path.join(StorageUtils.BASE_PATH, 'myapplog.debug'), mode='w',
                                        encoding="utf-8")
    debug_handler.setLevel(logging.DEBUG)

    info_handler = logging.FileHandler(f"{os.path.join(StorageUtils.BASE_PATH, 'myapp.log')}", encoding="utf-8")
    info_handler.setLevel(logging.INFO)

    log_level = logging.getLevelName(os.environ.get(LOG_LEVEL))
    logging.basicConfig(format='%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s',
                        datefmt='%d/%m/%Y %H:%M:%S',
                        level=log_level,
                        handlers=[
                            logging.StreamHandler(),
                            info_handler,
                            debug_handler
                        ])
    init_the_db()



if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)
