from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(f"Required environment variable '{key}' is not set.")
    return value


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


class Settings:
    SUPABASE_URL: str = _require("SUPABASE_URL")
    SUPABASE_KEY: str = _require("SUPABASE_KEY")

    CLAUDE_API_KEY: str = _require("CLAUDE_API_KEY")
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"

    DEEPL_API_KEY: str = _require("DEEPL_API_KEY")

    WP_URL: str = _require("WP_URL")
    WP_USER: str = _require("WP_USER")
    WP_APP_PASSWORD: str = _require("WP_APP_PASSWORD")

    GOOGLE_ADS_CLIENT_ID: str = _optional("GOOGLE_ADS_CLIENT_ID")
    GOOGLE_ADS_DEVELOPER_TOKEN: str = _optional("GOOGLE_ADS_DEVELOPER_TOKEN")

    GA_PROPERTY_ID: str = _require("GA_PROPERTY_ID")

    TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = _require("TELEGRAM_CHAT_ID")

    ADSENSE_PUBLISHER_ID: str = _optional("ADSENSE_PUBLISHER_ID")

    MEDIUM_INTEGRATION_TOKEN: str = _optional("MEDIUM_INTEGRATION_TOKEN")

    PINTEREST_ACCESS_TOKEN: str = _optional("PINTEREST_ACCESS_TOKEN")

    REDDIT_CLIENT_ID: str = _optional("REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET: str = _optional("REDDIT_CLIENT_SECRET")
    REDDIT_USERNAME: str = _optional("REDDIT_USERNAME")
    REDDIT_PASSWORD: str = _optional("REDDIT_PASSWORD")

    SUPPORTED_LANGUAGES: list[str] = ["en", "ja", "es", "pt"]
    ARTICLES_PER_DAY: int = 5
    AB_TEST_MIN_PV: int = 300
    AB_TEST_SIGNIFICANCE: float = 0.05
    ROI_SCALE_UP_THRESHOLD: float = 50.0
    ROI_HOLD_THRESHOLD: float = 10.0

    AMAZON_AFFILIATE_TAG: str = _optional("AMAZON_AFFILIATE_TAG", "")
    SHAREASALE_AFFILIATE_ID: str = _optional("SHAREASALE_AFFILIATE_ID", "")


settings = Settings()
