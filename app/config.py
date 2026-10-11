from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite:///data/app.db"
    audio_storage_dir: str = "storage/audio"
    max_file_size_bytes: int = 50 * MIB
    allowed_extensions: list[str] = [".wav", ".mp3"]

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def split_extensions(cls, value):
        if isinstance(value, str):
            return [ext.strip() for ext in value.split(",") if ext.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
