"""FastAPI monitoring and control endpoints."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from indeed_scraper.config import settings
from indeed_scraper.database import DatabaseManager

logger = logging.getLogger(__name__)

# Global state
db_manager: Optional[DatabaseManager] = None
proxy_pool = None
scheduler: Optional[AsyncIOScheduler] = None
coordinator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    global db_manager, proxy_pool, coordinator

    db_manager = DatabaseManager()
    await db_manager.initialize()

    from indeed_scraper.proxyManager import ProxyPool
    proxy_pool = ProxyPool()

    from indeed_scraper.scraperCoordinator import ScraperCoordinator
    coordinator = ScraperCoordinator(db_manager, proxy_pool)

    yield

    if db_manager:
        await db_manager.close()


app = FastAPI(
    title="Indeed Job Scraper API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check
@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    db_status = "connected"
    try:
        if db_manager:
            await db_manager.jobs.count_jobs()
    except Exception:
        db_status = "disconnected"

    return {
        "status": "ok",
        "db": db_status,
        "proxies": "alive" if proxy_pool and proxy_pool.providers else "no providers",
    }


# Job endpoints
@app.get("/api/jobs")
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    company: Optional[str] = None,
    location: Optional[str] = None,
    posted_within_days: Optional[int] = Query(None, ge=1),
):
    """List jobs with optional filters."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    jobs = await db_manager.jobs.list_jobs(
        skip=skip,
        limit=limit,
        company=company,
        location=location,
        posted_within_days=posted_within_days,
    )
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/api/jobs/{job_url:path}")
async def get_job(job_url: str):
    """Get single job by URL."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    job = await db_manager.jobs.get_job_by_url(job_url)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/count")
async def job_count():
    """Get total job count and duplicate statistics."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    stats = await db_manager.jobs.count_jobs()
    return stats


# Proxy endpoints
@app.get("/api/proxies")
async def list_proxies():
    """List proxy pool status."""
    if not proxy_pool:
        raise HTTPException(status_code=503, detail="Proxy pool not initialized")

    return proxy_pool.get_stats()


@app.post("/api/proxies/rotate")
async def rotate_proxies():
    """Force proxy rotation."""
    if not coordinator:
        raise HTTPException(status_code=503, detail="Coordinator not initialized")

    await coordinator.force_rotation()
    return {"status": "rotated"}


# Watermark endpoints
@app.get("/api/watermarks")
async def get_watermarks():
    """Get current scrape watermarks."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Return all watermarks (would need a list method, using placeholder)
    watermarks = []
    for scrape_type in ["search", "detail"]:
        wm = await db_manager.jobs.get_watermark(scrape_type)
        if wm:
            watermarks.append(wm)

    return {"watermarks": watermarks}


# Scrape trigger
@app.post("/api/scrape/trigger")
async def trigger_scrape(
    queries: Optional[str] = None,
    locations: Optional[str] = None,
):
    """Manually trigger a scrape cycle."""
    if not coordinator:
        raise HTTPException(status_code=503, detail="Coordinator not initialized")

    queries_list = [q.strip() for q in (queries or settings.SEARCH_QUERIES).split(";")]
    locations_list = [l.strip() for l in (locations or settings.LOCATIONS).split(";")]

    # Run async without waiting
    import asyncio
    asyncio.create_task(coordinator.run_scraping_cycle(queries_list, locations_list))

    return {"status": "triggered", "queries": queries_list, "locations": locations_list}


# Job stats summary
@app.get("/api/jobs/stats/summary")
async def job_stats_summary():
    """Get aggregate job statistics."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    total = await db_manager.jobs.count_jobs()

    # Get top companies (placeholder - would need aggregation query)
    return {
        "total_jobs": total.get("total", 0),
        "duplicates_caught": total.get("duplicates_caught", 0),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)