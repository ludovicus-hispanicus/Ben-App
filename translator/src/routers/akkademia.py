from typing import List

import akkadian.transliterate as akk
from fastapi import APIRouter, Form

router = APIRouter(
    prefix="/api/v1/akkademia",
    tags=["items"],
    responses={404: {"description": "Not found"}},
)


@router.post("/translate/")
async def convert_text(text: List[str] = Form(None)):
    print(f"translate text, {text}")
    result = [akk.transliterate_bilstm(line) for line in text]
    print("result is", result)

    return result
