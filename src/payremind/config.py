from functools import lru_cache
from typing import Any
from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Terraform creates SSM parameters with this placeholder until real values are set.
UNSET = "unset"
DEMO_SUPPLIER_GSTIN = "29ABCDE1234F1ZW"  # made up, valid check digit; demo invoices only


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYREMIND_", env_file=".env")

    database_url: str = "sqlite:///./payremind.db"
    # On AWS the URL is built from these; the password comes from the RDS-managed secret.
    db_host: str = ""
    db_port: int = 5432
    db_name: str = "payremind"
    db_user: str = "payremind"
    db_password: str = ""
    # Postgres schema for this environment (dev/test/staging/prod); "" = default search_path
    db_schema: str = ""
    # WhatsApp Cloud API. Leave empty in dev: the fake sender is used instead.
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_base: str = "https://graph.facebook.com/v21.0"
    whatsapp_app_secret: str = ""  # verifies webhook signatures
    whatsapp_verify_token: str = ""  # echoed during webhook subscription
    public_base_url: str = "http://localhost:8000"  # used to build pay page links
    # Keys OTP hashes. Required in production; if empty, a random per-process key is used,
    # so pending codes stop working after a restart.
    secret_key: str = ""
    # Local development: print WhatsApp messages and login codes to the log instead of
    # sending. Ignored whenever WhatsApp credentials are set.
    dev_log_messages: bool = False
    # Demo: one-click sign-in to the seeded demo business, a DEMO banner and a message outbox.
    # Refuses to start if real WhatsApp or Razorpay credentials are configured.
    demo_mode: bool = False
    cookie_secure: bool = True  # set false only for local http development
    session_days: int = 7
    # Razorpay (our own subscription fee). Plan ids come from the Razorpay dashboard.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_plan_starter: str = ""
    razorpay_plan_growth: str = ""
    # Supplier (us) on GST invoices. Leave gstin empty until registered: invoices then carry no GST.
    supplier_name: str = "PayRemind"
    supplier_gstin: str = ""
    supplier_state_code: str = "29"  # Karnataka
    supplier_address: str = ""
    max_upload_bytes: int = 5 * 1024 * 1024
    max_import_rows: int = 5000

    @model_validator(mode="before")
    @classmethod
    def _drop_placeholders(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: ("" if v == UNSET else v) for k, v in data.items()}
        return data  # pragma: no cover

    @model_validator(mode="after")
    def _demo_is_offline(self) -> "Settings":
        if self.demo_mode:
            if self.whatsapp_token or self.razorpay_key_id or self.razorpay_key_secret:
                raise ValueError("demo_mode cannot be used with real WhatsApp or Razorpay keys")
            if self.db_schema == "prod":
                raise ValueError("demo_mode cannot use the prod schema")
            self.dev_log_messages = True
            self.supplier_gstin = self.supplier_gstin or DEMO_SUPPLIER_GSTIN
        return self

    @model_validator(mode="after")
    def _build_database_url(self) -> "Settings":
        url = self.database_url
        # Accept URLs as Supabase and other hosts print them; always use psycopg and TLS.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+psycopg://" + url.removeprefix(prefix)
        if url.startswith("postgresql+psycopg://") and "sslmode=" not in url:
            url += ("&" if "?" in url else "?") + "sslmode=require"
        self.database_url = url
        if self.db_host:
            self.database_url = (
                f"postgresql+psycopg://{quote(self.db_user, safe='')}:"
                f"{quote(self.db_password, safe='')}@{self.db_host}:{self.db_port}/"
                f"{self.db_name}?sslmode=require"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
