from pathlib import Path
from uuid import UUID

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    app_url: HttpUrl
    app_timezone: str = "UTC"
    database_host: str = "db"
    database_port: int = 5432
    database_name: str = "expo"
    database_user: str = "expo"
    database_password_file: Path = Path("/run/secrets/db_password")
    host_id_file: Path = Path("/run/secrets/host_id")

    assets_dir: Path = Path("/data/assets")
    previews_dir: Path = Path("/data/previews")
    db_dir: Path = Path("/data/db")
    models_dir: Path = Path("/data/models")
    exports_dir: Path = Path("/data/exports")
    backup_dir: Path = Path("/data/backups")
    assets_volume_id: UUID
    previews_volume_id: UUID
    db_volume_id: UUID
    models_volume_id: UUID
    exports_volume_id: UUID
    backup_volume_id: UUID

    assets_free_floor_bytes: int = Field(default=5 * 1024**3, ge=0)
    storage_check_seconds: int = Field(default=30, ge=1, le=300)
    worker_interval_seconds: float = Field(default=1, ge=0.1, le=10)
    worker_stale_seconds: int = Field(default=45, ge=15)
    ollama_url: HttpUrl | None = None
    ollama_model: str = ""
    ollama_timeout_seconds: int = Field(default=600, ge=10, le=3600)
    image_limit_bytes: int = Field(default=100 * 1024**2, ge=1)
    pdf_limit_bytes: int = Field(default=400 * 1024**2, ge=1)
    pdf_page_limit: int = Field(default=200, ge=1, le=10000)
    encryption_key_file: Path = Path("/run/secrets/encryption_key")
    chatgpt_callback_bind: str = Field(default="127.0.0.1", pattern=r"^(127\.0\.0\.1|0\.0\.0\.0)$")
    chatgpt_callback_port: int = Field(default=1455, ge=0, le=65535)
    passwordless: bool = False
    session_days: int = Field(default=30, ge=1, le=90)
    embedding_model: str = Field(default="minilm", pattern="^(minilm|bge)$")
    export_ttl_days: int = Field(default=7, ge=1, le=90)
    embedding_service_url: str = "http://worker:8001"

    @field_validator("app_timezone")
    @classmethod
    def valid_timezone(cls, value):
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except KeyError:
            raise ValueError("Use a valid IANA timezone, such as Europe/London.") from None
        return value

    @property
    def internal_token(self) -> str:
        import hashlib

        return hashlib.sha256(
            self.encryption_key_file.read_bytes().strip()
            + b"/internal-embedding/"
            + str(self.host_id).encode()
        ).hexdigest()

    @field_validator("app_url")
    @classmethod
    def canonical_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("APP_URL must use https")
        if value.path not in (None, "/") or value.query or value.fragment:
            raise ValueError("APP_URL must be an origin without a path, query or fragment")
        if value.username or value.password:
            raise ValueError("APP_URL must not include credentials")
        return value

    @field_validator("ollama_url", mode="before")
    @classmethod
    def blank_ollama(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def canonical_origin(self) -> str:
        return str(self.app_url).rstrip("/")

    @property
    def host_id(self) -> UUID:
        return UUID(self.host_id_file.read_text(encoding="utf-8").strip())

    @property
    def database_url(self) -> URL:
        password = self.database_password_file.read_text(encoding="utf-8").strip()
        if len(password) < 24:
            raise ValueError("Database password file is missing a strong generated password")
        return URL.create(
            "postgresql+psycopg",
            username=self.database_user,
            password=password,
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )
