import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.owui_auth import normalize_session_token

# A JWT is three base64url segments separated by dots.
_JWT_RE = r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"


class AccountForm(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    target_url: str = Field(min_length=1, max_length=512)
    auth_mode: str = Field(default="password", pattern=r"^(password|token)$")
    email: str = Field(default="", max_length=256)
    password: str = Field(default="")
    session_token: str = Field(default="")
    model_prefix: str = Field(default="", max_length=64)

    @field_validator("session_token")
    @classmethod
    def _normalize_token(cls, v: str) -> str:
        return normalize_session_token(v)

    @model_validator(mode="after")
    def _check_credentials(self):
        if self.auth_mode == "token":
            if not self.session_token:
                raise ValueError("Token 模式需要填写 Session Token")
            if not re.match(_JWT_RE, self.session_token):
                raise ValueError("Session Token 格式无效，应为完整 JWT（可直接粘贴 token= 这一整段）")
        else:
            if not self.email.strip() or not self.password:
                raise ValueError("密码模式需要填写邮箱和密码")
        return self


class AccountUpdateForm(BaseModel):
    name: str | None = None
    target_url: str | None = None
    auth_mode: str | None = Field(default=None, pattern=r"^(password|token)$")
    email: str | None = None
    password: str | None = None
    session_token: str | None = None
    model_prefix: str | None = None
    is_enabled: bool | None = None

    @field_validator("session_token")
    @classmethod
    def _normalize_token(cls, v: str | None) -> str | None:
        return normalize_session_token(v) if v else v


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
