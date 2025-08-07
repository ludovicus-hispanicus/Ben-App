import time
from typing import Dict

import jwt
import os

JWT_SECRET = os.getenv("SECRET")
JWT_ALGORITHM = os.getenv("ALGORITHM")
HOUR_IN_SECONDS = 60 * 60
TOKEN_EXPIRY_TIME_IN_SECONDS = (HOUR_IN_SECONDS * 24) * 30


def token_response(token: str):
    return {
        "access_token": token
    }


def sign_jwt(user_id: str, is_admin: bool) -> Dict[str, str]:
    payload = {
        "user_id": user_id,
        "is_admin": is_admin,
        "expires": time.time() + TOKEN_EXPIRY_TIME_IN_SECONDS
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    return token_response(token)


def decode_jwt(token: str) -> dict:
    try:
        decoded_token = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return decoded_token if decoded_token["expires"] >= time.time() else None
    except:
        return {}
