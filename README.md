# Indeed Job Scraper

Scalable job scraper for Indeed.com with proxy rotation and hourly auto-refresh. Built with Scrapy + Playwright for high-quality data extraction.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    APScheduler (hourly trigger)                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┴──────────────────┐
         ▼                                     ▼
┌─────────────────────┐          ┌─────────────────────┐
│  Scrapy Spider      │          │  Domain Resolver     │
│  Job Discovery      │          │  URL canonicalization│
│  (ScraperAPI first) │          └──────────┬──────────┘
└─────────────────────┘                     │
                    ┌──────────────────────┴──────────────┐
                    ▼                                     ▼
         ┌──────────────────────────┐       ┌──────────────────────┐
         │  Playwright Detail       │       │  PostgreSQL + Redis   │
         │  Extractor (stealth JS)  │──────▶│  Deduplication       │
         │  Adaptive delays 3-8s    │       │  Unique constraint   │
         └──────────────────────────┘       └──────────────────────┘
                    │
                    ▼
         ┌──────────────────────────┐
         │  MongoDB (raw archive)     │
         │  Full job data retention  │
         └──────────────────────────┘
```

## Features

- **Hybrid Architecture** — Scrapy for fast discovery, Playwright for JavaScript-rendered detail pages
- **Proxy Rotation** — ScraperAPI → ProxyMesh tiered fallback with session/batch rotation
- **Auto-Refresh** — APScheduler hourly runs with watermark tracking (incremental, not full re-scrape)
- **Dedup** — PostgreSQL unique constraint on `(job_title, company_name, location)` prevents duplicates
- **Domain Resolution** — Canonicalizes employer URLs via Google search + alias mapping
- **Stealth** — `playwright-stealth`, rotating UA, adaptive delays (3-8s random)
- **Monitoring** — FastAPI endpoints + Prometheus metrics

## Tech Stack

| Component       | Technology |
|----------------|-----------|
| Spider          | Scrapy 2.x |
| JS Renderer     | Playwright (stealth) |
| Proxy           | ScraperAPI → ProxyMesh |
| Database        | PostgreSQL 15+ |
| Raw Archive     | MongoDB |
| API             | FastAPI + Uvicorn |
| Scheduler       | APScheduler |
| Metrics         | Prometheus |
| Container       | Docker Compose |

## Quick Start

```bash
git clone https://github.com/9KMan/JOB-20260524095349-000049.git
cd JOB-20260524095349-000049

python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m indeed_scraper.run
```

Or with Docker:

```bash
docker-compose up --build
```

## Environment Variables

| Variable                | Description                            |
|-------------------------|----------------------------------------|
| `SCRAPERAPI_KEY`        | ScraperAPI key for proxy rotation      |
| `PROXYMESH_URL`         | Backup ProxyMesh proxy URL             |
| `DATABASE_URL`          | PostgreSQL connection string            |
| `MONGODB_URI`           | MongoDB connection string              |
| `GOOGLE_API_KEY`        | Google search API for domain resolution |

## Project Structure

```
indeed_scraper/
├── run.py                  # APScheduler entry point
├── api.py                  # FastAPI endpoints + Prometheus metrics
├── database.py             # PostgreSQL + MongoDB storage
├── proxyManager.py         # Proxy rotation (ScraperAPI → ProxyMesh)
├── middlewares.py          # Scrapy UA rotation, retry delays
├── domainResolver.py       # Employer URL canonicalization
├── scraperCoordinator.py   # Orchestrates full scrape cycle
├── config.py               # Configuration loader
├── utils.py                # Shared utilities
├── spiders/
│   ├── searchSpider.py    # Job discovery via Scrapy
│   └── detailExtractor.py  # Playwright detail page extraction
tests/
└── test_scraper.py         # Basic integration tests
```

## API Endpoints

| Endpoint          | Method | Description                     |
|-------------------|--------|--------------------------------|
| `/api/jobs`       | GET    | Recent jobs (paginated)         |
| `/api/jobs?search=` | GET | Filter by keyword              |
| `/api/search?q=`  | GET    | Search jobs by title/company   |
| `/api/stats`      | GET    | Scrape stats + proxy status    |
| `/metrics`        | GET    | Prometheus metrics             |

## Monitoring

Prometheus scrape config in `prometheus.yml`. Key metrics:

- `jobs_scraped_total` — Total jobs extracted
- `scrape_duration_seconds` — Time per scrape cycle
- `dedup_skipped_total` — Duplicates blocked
- `proxy_error_total` — Proxy failures

Prometheus available at `http://localhost:9090/graph`.

## License

MIT