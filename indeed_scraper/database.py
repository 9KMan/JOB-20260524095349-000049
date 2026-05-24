"""Database abstraction layer supporting PostgreSQL and MongoDB."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any, AsyncIterator, Optional

from indeed_scraper.config import settings

logger = logging.getLogger(__name__)


class BaseJobRepository(ABC):
    """Abstract base class for job storage operations."""

    @abstractmethod
    async def insert_job(self, job: dict) -> bool:
        """Insert a job. Returns True if inserted, False if duplicate."""
        pass

    @abstractmethod
    async def job_exists(self, job_title: str, company_name: str, location: str) -> bool:
        """Check if a job with the given identity already exists."""
        pass

    @abstractmethod
    async def get_job_by_url(self, job_url: str) -> Optional[dict]:
        """Retrieve a job by its Indeed URL."""
        pass

    @abstractmethod
    async def list_jobs(
        self,
        skip: int = 0,
        limit: int = 50,
        company: Optional[str] = None,
        location: Optional[str] = None,
        posted_within_days: Optional[int] = None,
    ) -> list[dict]:
        """List jobs with optional filters."""
        pass

    @abstractmethod
    async def count_jobs(self) -> dict:
        """Return job count statistics."""
        pass

    @abstractmethod
    async def upsert_watermark(self, scrape_type: str, last_key: str):
        """Update the scrape watermark for a given type."""
        pass

    @abstractmethod
    async def get_watermark(self, scrape_type: str) -> Optional[dict]:
        """Get current watermark for a given scrape type."""
        pass

    @abstractmethod
    async def initialize(self):
        """Initialize database schema/indices."""
        pass

    @abstractmethod
    async def close(self):
        """Close database connections."""
        pass


class PostgresJobRepository(BaseJobRepository):
    """PostgreSQL implementation using asyncpg."""

    def __init__(self):
        self.conn: Optional[Any] = None

    async def initialize(self):
        import asyncpg
        self.conn = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
        )
        await self._ensure_schema()

    async def _ensure_schema(self):
        schema = """
        CREATE TABLE IF NOT EXISTS jobs (
            id            BIGSERIAL PRIMARY KEY,
            job_title     VARCHAR(500) NOT NULL,
            company_name  VARCHAR(300) NOT NULL,
            company_domain VARCHAR(255),
            job_url       VARCHAR(1000) UNIQUE,
            apply_url     VARCHAR(1000),
            description   TEXT,
            salary_range  VARCHAR(200),
            skills        TEXT[],
            experience    VARCHAR(200),
            location      VARCHAR(300),
            posted_date   DATE,
            scraped_at    TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_job_identity UNIQUE (job_title, company_name, location)
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_name);
        CREATE INDEX IF NOT EXISTS idx_jobs_location ON jobs(location);
        CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(posted_date);
        CREATE INDEX IF NOT EXISTS idx_jobs_scraped ON jobs(scraped_at);

        CREATE TABLE IF NOT EXISTS scrape_watermark (
            scrape_type   VARCHAR(50) PRIMARY KEY,
            last_key      VARCHAR(255),
            last_scraped  TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS proxy_metrics (
            proxy         VARCHAR(255) PRIMARY KEY,
            success_count INT DEFAULT 0,
            fail_count    INT DEFAULT 0,
            avg_latency_ms INT,
            last_used     TIMESTAMP
        );
        """
        await self.conn.execute(schema)

    async def insert_job(self, job: dict) -> bool:
        try:
            result = await self.conn.fetchrow(
                """
                INSERT INTO jobs (
                    job_title, company_name, company_domain, job_url, apply_url,
                    description, salary_range, skills, experience, location,
                    posted_date
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (job_title, company_name, location) DO NOTHING
                RETURNING id
                """,
                job["job_title"],
                job["company_name"],
                job.get("company_domain"),
                job["job_url"],
                job.get("apply_url"),
                job.get("description"),
                job.get("salary_range"),
                job.get("skills", []),
                job.get("experience"),
                job.get("location"),
                job.get("posted_date"),
            )
            return result is not None
        except Exception as e:
            logger.error(f"Failed to insert job: {e}")
            return False

    async def job_exists(self, job_title: str, company_name: str, location: str) -> bool:
        result = await self.conn.fetchrow(
            """
            SELECT 1 FROM jobs WHERE job_title=$1 AND company_name=$2 AND location=$3
            """,
            job_title, company_name, location,
        )
        return result is not None

    async def get_job_by_url(self, job_url: str) -> Optional[dict]:
        row = await self.conn.fetchrow("SELECT * FROM jobs WHERE job_url=$1", job_url)
        return dict(row) if row else None

    async def list_jobs(
        self,
        skip: int = 0,
        limit: int = 50,
        company: Optional[str] = None,
        location: Optional[str] = None,
        posted_within_days: Optional[int] = None,
    ) -> list[dict]:
        query = "SELECT * FROM jobs WHERE 1=1"
        params = []
        idx = 1

        if company:
            query += f" AND company_name ILIKE ${idx}"
            params.append(f"%{company}%")
            idx += 1

        if location:
            query += f" AND location ILIKE ${idx}"
            params.append(f"%{location}%")
            idx += 1

        if posted_within_days:
            query += f" AND posted_date >= CURRENT_DATE - INTERVAL '${idx} days'"
            params.append(posted_within_days)
            idx += 1

        query += f" ORDER BY posted_date DESC LIMIT ${idx} OFFSET ${idx + 1}"
        params.extend([limit, skip])

        rows = await self.conn.fetch(query, *params)
        return [dict(row) for row in rows]

    async def count_jobs(self) -> dict:
        total = await self.conn.fetchval("SELECT COUNT(*) FROM jobs")
        dup_count = await self.conn.fetchval("""
            SELECT COUNT(*) - COUNT(DISTINCT (job_title, company_name, location))
            FROM jobs
        """)
        return {"total": total, "duplicates_caught": max(0, dup_count)}

    async def upsert_watermark(self, scrape_type: str, last_key: str):
        await self.conn.execute(
            """
            INSERT INTO scrape_watermark (scrape_type, last_key, last_scraped)
            VALUES ($1, $2, NOW())
            ON CONFLICT (scrape_type) DO UPDATE SET last_key=$2, last_scraped=NOW()
            """,
            scrape_type, last_key,
        )

    async def get_watermark(self, scrape_type: str) -> Optional[dict]:
        row = await self.conn.fetchrow(
            "SELECT * FROM scrape_watermark WHERE scrape_type=$1",
            scrape_type,
        )
        return dict(row) if row else None

    async def close(self):
        if self.conn:
            await self.conn.close()


class MongoJobRepository(BaseJobRepository):
    """MongoDB implementation using motor (async)."""

    def __init__(self):
        self.client: Optional[Any] = None
        self.db: Optional[Any] = None

    async def initialize(self):
        from motor.motor_asyncio import AsyncIOMotorClient
        self.client = AsyncIOMotorClient(settings.MONGODB_URI)
        self.db = self.client[settings.MONGODB_DB]

        # Create unique compound index for deduplication
        await self.db.jobs.create_index(
            [("job_title", 1), ("company_name", 1), ("location", 1)],
            unique=True,
        )
        await self.db.jobs.create_index("job_url", unique=True)

    async def insert_job(self, job: dict) -> bool:
        try:
            # Add scraped_at timestamp
            job["scraped_at"] = datetime.utcnow()
            await self.db.jobs.insert_one(job)
            return True
        except Exception as e:
            if "duplicate key error" in str(e).lower():
                return False
            logger.error(f"Failed to insert job: {e}")
            return False

    async def job_exists(self, job_title: str, company_name: str, location: str) -> bool:
        count = await self.db.jobs.count_documents({
            "job_title": job_title,
            "company_name": company_name,
            "location": location,
        })
        return count > 0

    async def get_job_by_url(self, job_url: str) -> Optional[dict]:
        doc = await self.db.jobs.find_one({"job_url": job_url})
        return doc

    async def list_jobs(
        self,
        skip: int = 0,
        limit: int = 50,
        company: Optional[str] = None,
        location: Optional[str] = None,
        posted_within_days: Optional[int] = None,
    ) -> list[dict]:
        query = {}
        if company:
            query["company_name"] = {"$regex": company, "$options": "i"}
        if location:
            query["location"] = {"$regex": location, "$options": "i"}
        if posted_within_days:
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(days=posted_within_days)
            query["posted_date"] = {"$gte": cutoff}

        cursor = self.db.jobs.find(query).sort("posted_date", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def count_jobs(self) -> dict:
        total = await self.db.jobs.count_documents({})
        pipeline = [
            {"$group": {"_id": {"job_title": "$job_title", "company_name": "$company_name", "location": "$location"}}},
            {"$group": {"_id": None, "count": {"$sum": 1}}},
        ]
        unique_count = await self.db.jobs.aggregate(pipeline).to_list(1)
        dup_count = total - (unique_count[0]["count"] if unique_count else 0)
        return {"total": total, "duplicates_caught": max(0, dup_count)}

    async def upsert_watermark(self, scrape_type: str, last_key: str):
        await self.db.watermarks.update_one(
            {"scrape_type": scrape_type},
            {"$set": {"last_key": last_key, "last_scraped": datetime.utcnow()}},
            upsert=True,
        )

    async def get_watermark(self, scrape_type: str) -> Optional[dict]:
        return await self.db.watermarks.find_one({"scrape_type": scrape_type})

    async def close(self):
        if self.client:
            self.client.close()


class DatabaseManager:
    """Database manager factory returning the appropriate repository."""

    def __init__(self):
        self._repo: Optional[BaseJobRepository] = None

    async def initialize(self):
        if settings.DB_TYPE == "mongodb":
            self._repo = MongoJobRepository()
        else:
            self._repo = PostgresJobRepository()
        await self._repo.initialize()

    @property
    def jobs(self) -> BaseJobRepository:
        if self._repo is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._repo

    async def close(self):
        if self._repo:
            await self._repo.close()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[BaseJobRepository]:
        """Async context manager for database sessions."""
        if self._repo is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        yield self._repo