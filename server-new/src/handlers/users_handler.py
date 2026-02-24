from __future__ import annotations

from typing import Type

from fastapi import HTTPException
from pydantic import EmailStr

from api.dto.get_predictions import LoginDto
from entities.user import User, UserRole
from mongo.mongo_collection import MongoCollection


class UsersHandler:
    COLLECTION_NAME = "users"

    def __init__(self):
        self._collection = MongoCollection(collection_name=self.COLLECTION_NAME, obj_type=User)

    def get_user(self, login_request: LoginDto) -> User | None:
        return self._collection.find_one(find_filter={"email": login_request.email,
                                                      "password": login_request.password})

    def add_user(self, email: EmailStr, password: str, full_name: str, role: UserRole):
        existing_user = self._collection.find_one(find_filter={"email": email})
        if existing_user:
            raise HTTPException(status_code=500, detail="This email belongs to a user")

        self._collection.insert_one(obj=User(email=email, password=password, fullname=full_name, role=role))

    def delete_user(self, email: EmailStr):
        try:
            self._collection.delete_one(filter=dict(email=email))
        except Exception:
            raise HTTPException(status_code=500, detail=f"Failed to delete user {email}")

    def change_user_permissions(self, email: EmailStr, is_admin: bool):
        self._collection.update_one(query=dict(email=email),
                                    new_values=dict(role=UserRole.ADMIN.value if is_admin else UserRole.USER.value))

    def count(self):
        return self._collection.count()

    def list_all(self):
        return self._collection.find_many(find_filter={})
