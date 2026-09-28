"""Runtime settings from the environment (.env). Model/threshold config lives in config/."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/app.db"
    # Fernet key for the PII mapping: python -c "from cryptography.fernet import Fernet;
    # print(Fernet.generate_key().decode())"
    pii_encryption_key: str = ""
    session_secret: str = ""  # signs login cookies; any long random string
    secure_cookies: bool = True  # set false only for local http development
    data_dir: Path = ROOT / "data"
    max_upload_mb: int = 10
    max_files_per_run: int = 5
    retention_days: int = 30  # [D8]
    keep_audio: bool = False
    keep_raw_uploads: bool = False
    # Employer/client names are kept by default: they matter for the interview (spec 5.1)
    keep_organisation_names: bool = True
    runs_per_user_per_day: int = 5
    whisper_model: str = "small"  # faster-whisper size; [DECISION] small or medium
    # /healthz?deep=1 (external API reachability) requires this token in X-Health-Token
    health_token: str = ""
    # Public /demo page: link to the source code (empty = no link)
    demo_repo_url: str = ""


@lru_cache
def get_settings() -> Settings:
    # Also export .env into os.environ so provider keys are found outside Docker (Docker's
    # env_file already does this). Existing environment variables win.
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    return Settings()
