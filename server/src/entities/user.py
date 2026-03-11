from enum import Enum

from pydantic import EmailStr, Field
from pydantic.main import BaseModel

from api.dto.get_predictions import UserDto
from entities.new_text import DbModel


class UserRole(Enum):
    USER = 0
    ADMIN = 1


class User(DbModel):
    fullname: str = Field(...)
    email: EmailStr = Field(...)
    password: str = Field(...)
    role: UserRole = UserRole.USER

    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value

    class Config:
        json_schema_extra = {
            "example": {
                "fullname": "Abdulazeez Abdulazeez Adeshina",
                "email": "abdulazeez@x.com",
                "password": "weakpassword",
                "role": 0
            }
        }


class LoginResult(BaseModel):
    token: str
    user: UserDto
