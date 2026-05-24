"""Proxy rotation system with tiered fallback and failure tracking."""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Optional

from indeed_scraper.config import settings

logger = logging.getLogger(__name__)


class ProxyProvider:
    """Base class for proxy providers."""

    def get_proxy(self) -> Optional[str]:
        raise NotImplementedError

    def report_failure(self, proxy: str, status_code: int):
        pass


class ScraperAPIProvider(ProxyProvider):
    """ScraperAPI proxy provider."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_proxy(self) -> Optional[str]:
        if not self.api_key:
            return None
        return f"http://scraperapi:{self.api_key}@proxy.scraperapi.com:8001"


class ProxyMeshProvider(ProxyProvider):
    """ProxyMesh proxy provider with sticky sessions."""

    def __init__(self, user: str, password: str, proxies: list[str]):
        self.user = user
        self.password = password
        self.proxies = proxies or []
        self.current_index = 0

    def get_proxy(self) -> Optional[str]:
        if not self.user or not self.password:
            return None
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_index % len(self.proxies)]
        self.current_index += 1
        return f"http://{self.user}:{self.password}@{proxy}"


class ProxyPool:
    """Thread-safe proxy pool with failure tracking and rotation."""

    def __init__(self):
        self._lock = threading.Lock()
        self._failure_counts: dict[str, int] = defaultdict(int)
        self._blacklist: dict[str, float] = {}  # proxy -> unblock timestamp
        self._success_counts: dict[str, int] = defaultdict(int)
        self._last_used: dict[str, float] = {}

        self.providers: list[ProxyProvider] = []
        self._init_providers()

    def _init_providers(self):
        """Initialize proxy providers from settings."""
        # ScraperAPI (primary - auto-retries + JS rendering)
        if settings.SCRAPERAPI_KEY:
            self.providers.append(ScraperAPIProvider(settings.SCRAPERAPI_KEY))
            logger.info("ScraperAPI proxy provider initialized")

        # ProxyMesh (secondary)
        if settings.PROXYMESH_USER and settings.PROXYMESH_PASS:
            proxies = settings.get_proxies()
            self.providers.append(ProxyMeshProvider(
                settings.PROXYMESH_USER,
                settings.PROXYMESH_PASS,
                proxies,
            ))
            logger.info(f"ProxyMesh provider initialized with {len(proxies)} proxies")

        if not self.providers:
            logger.warning("No proxy providers configured - running without proxies")

    def get_proxy(self) -> Optional[str]:
        """Get next available proxy from the pool."""
        with self._lock:
            self._cleanup_blacklist()

            for provider in self.providers:
                proxy = provider.get_proxy()
                if proxy and proxy not in self._blacklist:
                    self._last_used[proxy] = time.time()
                    return proxy

            # Fallback: return None (direct connection)
            return None

    def report_failure(self, proxy: str, status_code: int):
        """Report proxy failure, potentially blacklisting it."""
        with self._lock:
            self._failure_counts[proxy] += 1

            if status_code in (403, 429):
                # Blacklist for 5 minutes on blocking responses
                self._blacklist[proxy] = time.time() + 300
                logger.warning(f"Proxy {proxy} blacklisted for 5min (status {status_code})")
            elif self._failure_counts[proxy] >= 5:
                # Blacklist for 1 minute after 5 consecutive failures
                self._blacklist[proxy] = time.time() + 60
                logger.warning(f"Proxy {proxy} blacklisted for 1min (5 consecutive failures)")

    def report_success(self, proxy: str):
        """Report successful use of a proxy."""
        with self._lock:
            self._success_counts[proxy] += 1
            self._failure_counts[proxy] = 0

    def _cleanup_blacklist(self):
        """Remove expired entries from blacklist."""
        now = time.time()
        self._blacklist = {p: t for p, t in self._blacklist.items() if t > now}

    def get_stats(self) -> dict:
        """Return proxy performance statistics."""
        with self._lock:
            stats = []
            all_proxies = set(self._success_counts.keys()) | set(self._failure_counts.keys())
            for proxy in all_proxies:
                stats.append({
                    "proxy": proxy,
                    "successes": self._success_counts.get(proxy, 0),
                    "failures": self._failure_counts.get(proxy, 0),
                    "blacklisted": proxy in self._blacklist,
                    "last_used": self._last_used.get(proxy),
                })
            return {"proxies": stats, "total_providers": len(self.providers)}

    def reload_proxies(self):
        """Reload proxy list from file (for SIGHUP)."""
        self._init_providers()
        logger.info("Proxy list reloaded")