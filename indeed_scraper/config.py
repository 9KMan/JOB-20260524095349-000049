"""Configuration management via environment variables."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _env(key: str, default: Optional[str] = None) -> str:
    val = os.environ.get(key, default)
    if val is None:
        raise ValueError(f"Required environment variable {key} is not set")
    return val


def _env_int(key: str, default: Optional[int] = None) -> int:
    val = os.environ.get(key)
    if val is None:
        if default is not None:
            return default
        raise ValueError(f"Required environment variable {key} is not set")
    return int(val)


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        # Scraper
        self.INDEED_BASE_URL = _env("INDEED_BASE_URL", "https://www.indeed.com")
        self.SEARCH_QUERIES = _env("SEARCH_QUERIES", "python developer;data engineer;machine learning")
        self.LOCATIONS = _env("LOCATIONS", "Remote;New York, NY;San Francisco, CA")
        self.SCHEDULE_INTERVAL_HOURS = _env_int("SCHEDULE_INTERVAL_HOURS", 1)

        # Database
        self.DB_TYPE = os.environ.get("DB_TYPE", "postgres").lower()
        self.POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
        self.POSTGRES_PORT = _env_int("POSTGRES_PORT", 5432)
        self.POSTGRES_DB = _env("POSTGRES_DB", "indeed_scraper")
        self.POSTGRES_USER = _env("POSTGRES_USER", "scraper")
        self.POSTGRES_PASSWORD = _env("POSTGRES_PASSWORD")
        self.MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
        self.MONGODB_DB = os.environ.get("MONGODB_DB", "indeed_scraper")

        # Proxy
        self.PROXYMESH_USER = os.environ.get("PROXYMESH_USER")
        self.PROXYMESH_PASS = os.environ.get("PROXYMESH_PASS")
        self.SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")
        self.PROXY_LIST_PATH = os.environ.get("PROXY_LIST_PATH", "proxies.txt")

        # Domain resolution
        self.GOOGLE_SEARCH_KEY = os.environ.get("GOOGLE_SEARCH_KEY")

        # Logging
        self.LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

        # Paths
        self.BASE_DIR = Path(__file__).resolve().parent.parent

    def get_postgres_dsn(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    def get_proxies(self) -> list[str]:
        path = self.BASE_DIR / self.PROXY_LIST_PATH
        if not path.exists():
            return []
        with open(path) as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]


settings = Settings()