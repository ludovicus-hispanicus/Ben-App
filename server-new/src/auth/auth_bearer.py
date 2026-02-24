from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .auth_handler import decode_jwt


class JWTBearer(HTTPBearer):
    def __init__(self, admin_required: bool = False, auto_error: bool = True):
        super(JWTBearer, self).__init__(auto_error=auto_error)
        self._admin_required = admin_required

    async def __call__(self, request: Request):
        credentials: HTTPAuthorizationCredentials = await super(JWTBearer, self).__call__(request)
        if credentials:
            if not credentials.scheme == "Bearer":
                raise HTTPException(status_code=403, detail="Invalid authentication scheme.")
            if not self.verify_jwt(credentials.credentials, admin_required=self._admin_required):
                raise HTTPException(status_code=403, detail="Invalid token or expired token.")
            return credentials.credentials
        else:
            raise HTTPException(status_code=403, detail="Invalid authorization code.")

    @staticmethod
    def verify_jwt(jwt_token: str, admin_required: bool = False) -> bool:
        try:
            payload = decode_jwt(jwt_token)
            if payload:
                if admin_required:
                    return payload["is_admin"]

                return True
        except:
            pass

        return False
