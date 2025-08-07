from fastapi import APIRouter

from api.dto.get_predictions import GetPredictionDto
from common.global_handlers import global_ai_handler
from utils.image_utils import ImageUtils

router = APIRouter(
    prefix="/api/v1/detexify",
    tags=["items"],
    # dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)


@router.post("/singleGuess")
async def single_guess(dto: GetPredictionDto):
    img = dto.image
    a = ImageUtils.convert_base64_to_np(img)
    result = global_ai_handler.get_detexify_predictions(np_img=a)
    return result
