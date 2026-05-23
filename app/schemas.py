from pydantic import BaseModel, Field


class AccountForm(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    target_url: str = Field(min_length=1, max_length=512)
    session_token: str = Field(min_length=1)


class AccountUpdateForm(BaseModel):
    name: str | None = None
    target_url: str | None = None
    session_token: str | None = None
    is_enabled: bool | None = None


class UserForm(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6)
    role: str = Field(default="user", pattern=r"^(admin|user)$")


class UserUpdateForm(BaseModel):
    password: str | None = Field(default=None, min_length=6)
    role: str | None = Field(default=None, pattern=r"^(admin|user)$")
    is_active: bool | None = None


class ApiKeyForm(BaseModel):
    name: str | None = None
    account_id: int
