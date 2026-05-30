from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite+aiosqlite:///./data/proxy.db"
    jwt_secret: str
    session_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 72
    bcrypt_rounds: int = 12
    default_admin_email: str = "admin@example.com"
    default_admin_password: str
    request_timeout: float = 120.0
    # Optional dedicated key for encrypting stored account passwords.
    # When empty, a key is derived from session_secret.
    encryption_key: str = ""


settings = Settings()
