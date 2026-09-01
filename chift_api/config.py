# Loads Hyperline API keys and sandbox/prod URL from .env.
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    hyperline_api_key: str
    hyperline_base_url: str
    hyperline_env: str = "test"

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.getenv("HYPERLINE_ENV", "test").strip().lower()
        if env not in {"test", "prod"}:
            raise ValueError("HYPERLINE_ENV must be 'test' or 'prod'")

        suffix = env.upper()
        api_key = os.getenv(f"HYPERLINE_API_KEY_{suffix}", "").strip()
        default_url = (
            "https://sandbox.api.hyperline.co"
            if env == "test"
            else "https://api.hyperline.co"
        )
        base_url = os.getenv(f"HYPERLINE_BASE_URL_{suffix}", default_url).rstrip("/")

        if not api_key:
            raise ValueError(
                f"Missing HYPERLINE_API_KEY_{suffix}. "
                f"Set HYPERLINE_ENV=test|prod and the matching key in .env"
            )

        return cls(
            hyperline_api_key=api_key,
            hyperline_base_url=base_url,
            hyperline_env=env,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
