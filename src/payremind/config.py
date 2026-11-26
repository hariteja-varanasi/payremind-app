from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYREMIND_", env_file=".env")

    database_url: str = "sqlite:///./payremind.db"
    # WhatsApp Cloud API. Leave empty in dev: the fake sender is used instead.
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_base: str = "https://graph.facebook.com/v21.0"
    max_upload_bytes: int = 5 * 1024 * 1024
    max_import_rows: int = 5000


@lru_cache
def get_settings() -> Settings:
    return Settings()
