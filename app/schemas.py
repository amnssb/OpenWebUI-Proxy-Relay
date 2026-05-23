from pydantic import BaseModel, Field


class AccountForm(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    target_url: str = Field(min_length=1, max_length=512)
    email: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1)
    model_prefix: str = Field(default="", max_length=64)


class AccountUpdateForm(BaseModel):
    name: str | None = None
    target_url: str | None = None
    email: str | None = None
    password: str | None = None
    model_prefix: str | None = None
    is_enabled: bool | None = None


class UserForm(BaseModel):
    email: str = Field(min_length=5, max_length=128)
    password: str = Field(min_length=6)
    role: str = Field(default="user", pattern=r"^(admin|user)$")


class UserUpdateForm(BaseModel):
    password: str | None = Field(default=None, min_length=6)
    role: str | None = Field(default=None, pattern=r"^(admin|user)$")
    is_active: bool | None = None


class ApiKeyForm(BaseModel):
    name: str | None = None
    account_id: int
