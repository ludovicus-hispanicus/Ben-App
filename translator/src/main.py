import logging
import time

import uvicorn
from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from routers import akkademia

origins = [
    "*",
]

app = FastAPI()
app.include_router(akkademia.router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()

    logging.debug("=============================")
    logging.debug(f">> request from ip {request.client.host}:{request.client.port} <<")

    logging.info(f"{request.method} {request.url}")
    response = await call_next(request)

    process_time = time.time() - start_time
    logging.info(f"Process time: {str(process_time)}")
    logging.debug("=============================")
    return response


@app.on_event("startup")
def startup_event():
    print("startup event...")
    logging.basicConfig(format='%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s',
                        datefmt='%d/%m/%Y %H:%M:%S',
                        level=logging.DEBUG,
                        handlers=[
                            logging.StreamHandler()
                        ])


if __name__ == '__main__':
    uvicorn.run(app, host="localhost", port=5002)
