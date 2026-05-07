from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    login: str = Field(min_length=3, max_length=50)
    password: str


class UserIn(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=30)
    password: str


class SignupIn(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=30)
    password: str
    turnstile_token: str
    website: str | None = None


class EmailUpdateIn(BaseModel):
    email: EmailStr


class ThoughtIn(BaseModel):
    content: str


class PasswordUpdate(BaseModel):
    old_password: str
    new_password: str
    new_password2: str


class VisibilityUpdate(BaseModel):
    strings_public: bool


class ResetRequestIn(BaseModel):
    email: EmailStr

class TimezoneIn(BaseModel):
    timezone: str
