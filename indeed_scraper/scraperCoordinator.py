"""Coordinator managing the scraping workflow."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from indeed_scraper.domainResolver import DomainResolver
from indeed_scraper.proxyManager import ProxyPool
from indeed_scraper.spiders.detailExtractor import PlaywrightDetailExtractor

logger = logging.getLogger(__name__)


class ScraperCoordinator:
    """Orchestrates the full scraping workflow."""

    def __init__(self, db, proxy_pool: ProxyPool, full_scrape: bool = False):
        self.db = db
        self.proxy_pool = proxy_pool
        self.full_scrape = full_scrape
        self.domain_resolver = DomainResolver()
        self._extractor: Optional[PlaywrightDetailExtractor] = None

    async def run_scraping_cycle(self, queries: list[str], locations: list[str]):
        """Run the complete scraping workflow."""
        from indeed_scraper.spiders.searchSpider import IndeedSearchSpider

        logger.info(f"Starting scraping cycle (full_scrape={self.full_scrape})")
        logger.info(f"Queries: {queries}, Locations: {locations}")

        # Initialize the detail extractor
        proxy = self.proxy_pool.get_proxy()
        self._extractor = PlaywrightDetailExtractor(proxy=proxy)
        await self._extractor.initialize()

        try:
            # Phase 1: Discovery via Scrapy
            discovered_jobs = await self._run_discovery(queries, locations)

            logger.info(f"Discovered {len(discovered_jobs)} jobs")

            # Phase 2: Detail extraction
            processed_count = 0
            for job in discovered_jobs:
                if await self._process_job(job):
                    processed_count += 1

            logger.info(f"Processed {processed_count} jobs successfully")

        finally:
            await self._extractor.close()

    async def _run_discovery(self, queries: list[str], locations: list[str]) -> list[dict]:
        """Run the Scrapy spider for job discovery."""
        import scrapy
        from scrapy.crawler import CrawlerProcess
        from twisted.internet import reactor

        jobs = []

        def handle_job(item):
            jobs.append(dict(item))

        # Run spider in Twisted reactor
        process = CrawlerProcess(settings={
            "LOG_LEVEL": "INFO",
            "USER_AGENT": "Mozilla/5.0 (compatible; IndeedBot/1.0)",
        })

        crawler = process.create_crawler(IndeedSearchSpider)
        crawler.signals.connect(handle_job, signal=scrapy.signals.item_scraped)

        process.crawl(crawler, queries=queries, locations=locations)
        process.start()

        return jobs

    async def _process_job(self, job: dict) -> bool:
        """Process a single job: extract details, resolve domain, deduplicate, store."""
        try:
            job_key = job.get("job_key")
            job_url = job.get("job_url")

            # Check if already processed (dedup)
            existing = await self.db.jobs.get_job_by_url(job_url)
            if existing:
                logger.debug(f"Job {job_key} already exists, skipping")
                return False

            # Extract full details via Playwright
            details = await self._extractor.extract_job_details(job_url)
            if not details:
                logger.warning(f"Failed to extract details for {job_key}")
                return False

            # Merge with discovered data
            job.update(details)

            # Resolve company domain
            company_domain = self.domain_resolver.get_canonical_domain(
                job.get("company_name", ""),
                job.get("apply_url"),
            )
            job["company_domain"] = company_domain

            # Ensure mandatory fields
            if not job.get("job_title") or not job.get("company_name"):
                logger.warning(f"Job {job_key} missing mandatory fields, skipping")
                return False

            # Insert into database
            inserted = await self.db.jobs.insert_job(job)
            if inserted:
                logger.info(f"Inserted job: {job['job_title']} @ {job['company_name']}")
                return True
            else:
                logger.debug(f"Duplicate job: {job['job_title']} @ {job['company_name']}")
                return False

        except Exception as e:
            logger.error(f"Error processing job {job.get('job_key')}: {e}")
            return False

    async def force_rotation(self):
        """Force proxy rotation."""
        self.proxy_pool.reload_proxies()
        if self._extractor:
            await self._extractor.close()
            proxy = self.proxy_pool.get_proxy()
            self._extractor = PlaywrightDetailExtractor(proxy=proxy)
            await self._extractor.initialize()