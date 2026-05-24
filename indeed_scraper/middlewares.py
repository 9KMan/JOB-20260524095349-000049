"""Custom Scrapy middlewares for proxy rotation and stealth."""
from __future__ import annotations

import logging
import random
from typing import Optional

from scrapy import signals
from scrapy.http import Request, Response
from scrapy.downloadermiddlewares.retry import RetryMiddleware

logger = logging.getLogger(__name__)

# Realistic user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


class ProxyRotationMiddleware:
    """Middleware to rotate proxies on each request batch."""

    def __init__(self, proxy_pool):
        self.proxy_pool = proxy_pool
        self.request_count = 0
        self.batch_size = 10

    @classmethod
    def from_crawler(cls, crawler):
        # Late import to avoid circular dependencies
        from indeed_scraper.proxyManager import ProxyPool
        pool = ProxyPool()
        mw = cls(pool)
        crawler.signals.connect(mw.spider_closed, signal=signals.spider_closed)
        return mw

    def process_request(self, request: Request, spider):
        """Add proxy to request if available."""
        self.request_count += 1

        if self.request_count % self.batch_size == 0:
            # Rotate proxy on batch boundary
            proxy = self.proxy_pool.get_proxy()
            if proxy:
                logger.debug(f"Rotating proxy: {proxy}")
                request.meta["proxy"] = proxy

        return None

    def process_response(self, request: Request, response: Response, spider):
        """Handle response and report proxy status."""
        proxy = request.meta.get("proxy")
        if proxy:
            if response.status in (403, 429):
                self.proxy_pool.report_failure(proxy, response.status)
            else:
                self.proxy_pool.report_success(proxy)

        return response

    def spider_closed(self, spider):
        logger.info(f"Proxy rotation middleware closed for {spider.name}")


class UserAgentMiddleware:
    """Middleware to rotate User-Agent headers."""

    def __init__(self):
        self.user_agents = USER_AGENTS

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_request(self, request: Request, spider):
        """Set random User-Agent."""
        request.headers["User-Agent"] = random.choice(self.user_agents)
        return None


class StealthMiddleware:
    """Middleware to add stealth headers and behavior."""

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_request(self, request: Request, spider):
        """Add stealth headers."""
        request.headers["Accept-Language"] = "en-US,en;q=0.9"
        request.headers["Accept-Encoding"] = "gzip, deflate, br"
        request.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        request.headers["Upgrade-Insecure-Requests"] = "1"
        return None

    def process_response(self, request: Request, response: Response, spider):
        return response


class CustomRetryMiddleware(RetryMiddleware):
    """Custom retry middleware that rotates proxy on 403/429."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.proxy_pool = None

    @classmethod
    def from_crawler(cls, crawler):
        from indeed_scraper.proxyManager import ProxyPool
        mw = super().from_crawler(crawler)
        mw.proxy_pool = ProxyPool()
        return mw

    def _retry(self, request: Request, reason: str, spider) -> Optional[Request]:
        """Retry with proxy rotation on blocking responses."""
        retryreq = super()._retry(request, reason, spider)
        if retryreq and request.meta.get("proxy"):
            # Rotate proxy on retry
            new_proxy = self.proxy_pool.get_proxy()
            if new_proxy:
                retryreq.meta["proxy"] = new_proxy
        return retryreq