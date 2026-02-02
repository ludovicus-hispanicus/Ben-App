from typing import List

import uuid
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import EmailStr

# Auth removed for desktop app
# from auth.auth_bearer import JWTBearer
# from auth.auth_handler import sign_jwt
from api.dto.get_predictions import LoginDto, UserDto
from common.global_handlers import global_users_handler
from entities.user import LoginResult, User, UserRole
import logging

router = APIRouter(
    prefix="/api/v1/users",
    tags=["items"],
    responses={404: {"description": "Not found"}},
)


@router.get("/list")
async def list_users() -> List[UserDto]:
    users = global_users_handler.list_all()
    return [UserDto(email=user.email, name=user.fullname, admin=user.is_admin()) for user in users]


@router.post("/create")
async def create_user(request: Request, user: UserDto = Body(...)):
    logging.info(f"Creating user {user.email} (by {request.state.user_id})...")

    password = uuid.uuid4().hex.lower()[0:10]

    role = UserRole.ADMIN if user.admin else UserRole.USER
    try:
        global_users_handler.add_user(email=user.email, password=password, full_name=user.name, role=role)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create user")

    return password


@router.get("/changePermissions/{email}/{is_admin}")
async def change_permissions(request: Request, email: EmailStr, is_admin: bool):
    logging.info(f"Changing {email} to admin:{is_admin} (by {request.state.user_id})...")

    try:
        global_users_handler.change_user_permissions(email=email, is_admin=is_admin)
    except Exception as e:
        logging.exception(e)
        raise HTTPException(status_code=500, detail="Failed to change user permissions")


@router.get("/delete/{email}")
async def delete_user(request: Request, email: EmailStr):
    logging.info(f"Deleting user {email} (by {request.state.user_id})...")

    try:
        global_users_handler.delete_user(email=email)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete user")


@router.post("/login", tags=["user"])
async def user_login(user: LoginDto = Body(...)):
    # Desktop app - auto-login without authentication
    logging.info(f"Desktop app login - auto-accepting user")
    return LoginResult(
        user=UserDto(email="desktop@local",
                     name="Desktop User",
                     admin=True),
        token="desktop-app-token"
    )
