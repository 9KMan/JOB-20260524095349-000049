#!/usr/bin/env python3
"""Indeed Job Scraper - Main entry point."""
import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from indeed_scraper.scraperCoordinator import ScraperCoordinator
from indeed_scraper.database import DatabaseManager
from indeed_scraper.proxyManager import ProxyPool
from indeed_scraper.config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_scheduler(coordinator: ScraperCoordinator) -> AsyncIOScheduler:
    """Create APScheduler configured for hourly runs."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        coordinator.run_scraping_cycle,
        "interval",
        hours=settings.SCHEDULE_INTERVAL_HOURS,
        args=[settings.SEARCH_QUERIES, settings.LOCATIONS],
        id="indeed_hourly_scrape",
        replace_existing=True,
        next_run_time=datetime.now(),  # run immediately on start
    )
    return scheduler


async def run_once(coordinator: ScraperCoordinator, queries: list[str], locations: list[str]):
    """Run a single scraping cycle and exit."""
    logger.info("Running single scraping cycle...")
    await coordinator.run_scraping_cycle(queries, locations)
    logger.info("Scraping cycle complete.")


async def main():
    parser = argparse.ArgumentParser(description="Indeed Job Scraper")
    parser.add_argument("--mode", choices=["scheduled", "once"], default="scheduled")
    parser.add_argument("--full", action="store_true", help="Force full re-scrape (ignore watermarks)")
    parser.add_argument("--queries", help="Comma-separated search queries (overrides env)")
    parser.add_argument("--locations", help="Comma-separated locations (overrides env)")
    args = parser.parse_args()

    # Override from CLI args if provided
    queries = [q.strip() for q in (args.queries or settings.SEARCH_QUERIES).split(";")]
    locations = [l.strip() for l in (args.locations or settings.LOCATIONS).split(";")]

    db = DatabaseManager()
    await db.initialize()
    logger.info(f"Database initialized: {settings.DB_TYPE}")

    proxy_pool = ProxyPool()
    coordinator = ScraperCoordinator(db, proxy_pool, full_scrape=args.full)

    if args.mode == "once":
        await run_once(coordinator, queries, locations)
        await db.close()
        return

    # Scheduled mode
    scheduler = create_scheduler(coordinator)
    scheduler.start()
    logger.info(f"Scheduler started. Running every {settings.SCHEDULE_INTERVAL_HOURS} hour(s).")

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def shutdown_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    try:
        await shutdown_event.wait()
    finally:
        scheduler.shutdown()
        await db.close()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())