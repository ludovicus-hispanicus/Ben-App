from fastapi import APIRouter
import requests

router = APIRouter(
    prefix="/api/v1/about",
    tags=["items"],
    responses={404: {"description": "Not found"}},
)

@router.get("/readme")
async def get_readme() -> str:
    # fetch readme.md from github https://github.com/DigitalPasts/BEn/blob/main/README.md
    url = "https://raw.githubusercontent.com/DigitalPasts/BEn/main/README.md"
    response = requests.get(url)
    return response.text


