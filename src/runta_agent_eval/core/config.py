from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Settings:
    runta_token: str
    openai_api_key: str
    openai_model: str
    openai_api_url: str
    app_host: str
    app_port: int
    database_path: Path
    artifact_dir: Path
    experiment_dir: Path
    runta_vcpus: int
    runta_memory_mib: int
    runta_memory_max_mib: int
    runta_keep_runtimes: bool
    runta_secret_name: str
    runta_idle_suspend_secs: int
    max_candidates: int
    agent_max_steps: int


async def load_settings() -> Settings:
    try:
        load_dotenv()
        return Settings(
            runta_token=os.getenv("RUNTA_TOKEN", "").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
            openai_api_url=os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/responses").strip(),
            app_host=os.getenv("APP_HOST", "0.0.0.0").strip(),
            app_port=int(os.getenv("APP_PORT", "8000")),
            database_path=Path(os.getenv("DATABASE_PATH", "./runta_eval.sqlite3")).expanduser(),
            artifact_dir=Path(os.getenv("ARTIFACT_DIR", "./artifacts")).expanduser(),
            experiment_dir=Path(os.getenv("EXPERIMENT_DIR", "./experiments")).expanduser(),
            runta_vcpus=int(os.getenv("RUNTA_VCPUS", "1")),
            runta_memory_mib=int(os.getenv("RUNTA_MEMORY_MIB", "1024")),
            runta_memory_max_mib=int(os.getenv("RUNTA_MEMORY_MAX_MIB", "2048")),
            runta_keep_runtimes=os.getenv("RUNTA_KEEP_RUNTIMES", "true").strip().lower() in {"1", "true", "yes", "on"},
            runta_secret_name=os.getenv("RUNTA_SECRET_NAME", "openai-api-key").strip(),
            runta_idle_suspend_secs=int(os.getenv("RUNTA_IDLE_SUSPEND_SECS", "0")),
            max_candidates=int(os.getenv("MAX_CANDIDATES", "12")),
            agent_max_steps=int(os.getenv("AGENT_MAX_STEPS", "24")),
        )
    except Exception:
        logger.exception("Failed to load settings")
        raise
