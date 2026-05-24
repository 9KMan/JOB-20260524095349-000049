# Indeed Job Scraper — Specification

## 1. Project Overview

**Client:** Freelancer.com — "Scalable Indeed Job Scraper"
**Core Deliverables:**
- Production-ready Indeed scraper with proxy rotation
- Hourly auto-refresh (cron-based scheduler)
- Fields: job title, company name, company website, full description, salary, skills, experience, location, apply URL, posted date
- Mandatory fields: job title + company name (no misses allowed)
- Duplicate detection against existing dataset
- Company domain lookup when not listed on Indeed
- PostgreSQL OR MongoDB storage (client choice)
- Step-by-step deployment guide

**Tech Stack:** Python 3.11+, Scrapy + Playwright (hybrid), PostgreSQL or MongoDB, ProxyMesh/ScraperAPI rotation, Docker Compose, GitHub Actions CI/CD

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INDEED JOB SCRAPER                                  │
│                         ────────────────────                                 │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐    │
│   │  APScheduler │────▶│  Coordinator │────▶│  Scraper Workers (N)     │    │
│   │  (hourly)    │     │  (Queue Mgmt)│     │  [Scrapy + Playwright]   │    │
│   └──────────────┘     └──────┬───────┘     └───────────┬──────────────┘    │
│                               │                          │                    │
│                               ▼                          ▼                    │
│   ┌──────────────┐     ┌──────────────┐         ┌──────────────────────┐    │
│   │  Proxy       │     │  Deduplication│         │  Anti-Bot Layer      │    │
│   │  Rotator     │◀───▶│  Engine       │◀──────▶│  (stealth headers,   │    │
│   │  (ProxyMesh/ │     │  (job_title+  │         │   adaptive delays,   │    │
│   │   ScraperAPI)│     │   company PK) │         │   session rotation)  │    │
│   └──────┬───────┘     └──────────────┘         └──────────────────────┘    │
│          │                                                            │       │
│          ▼                                                            ▼       │
│   ┌──────────────┐                                           ┌───────────┐ │
│   │  Domain      │                                           │  Storage  │ │
│   │  Resolver     │                                           │  (Postgres │ │
│   │  (apply URL   │                                           │  or Mongo) │ │
│   │   parsing +   │                                           └─────┬─────┘ │
│   │   search pass)│                                                 │       │
│   └──────────────┘                                                 ▼       │
│                                                          ┌──────────────┐   │
│                                                          │  Dashboard   │   │
│                                                          │  (optional)  │   │
│                                                          └──────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

─────────────────── PROXY ROTATION DETAIL ────────────────────

┌────────────────────────────────────────────────────────────────────────────┐
│                    PROXY ROTATOR                                        │
│  ┌──────────────────────────────────────────────────────────────────┐     │
│  │  ProxyPool: [proxy_1, proxy_2, ..., proxy_N]                    │     │
│  │  Strategy: round-robin OR failures-adaptive                     │     │
│  │  Fallback: ScraperAPI → ProxyMesh → free proxies               │     │
│  └──────────────────────────────────────────────────────────────────┘     │
│                              │                                            │
│                              ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────┐     │
│  │  Per-request proxy selection                                     │     │
│  │  • Rotate on every N requests (configurable batch size)          │     │
│  │  • Rotate on HTTP 403/429/captcha response                        │     │
│  │  • Session-boundary rotation (new proxy per session)              │     │
│  └──────────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────────┘

─────────────────── SCRAPING FLOW ────────────────────

┌────────────────────────────────────────────────────────────────────────────┐
│  1. URL Discovery (Scrapy Spider — breadth-first)                          │
│     indeed.com/jobs?q={query}&l={location}                                 │
│     → Extract: job_key, job_title, company_name, location, posted_date      │
│     → enqueue_if_new(job_key)                                               │
│                                                                            │
│  2. Detail Extraction (Playwright — headless Chrome stealth)                │
│     indeed.com/rc/jobs?jobkey={job_key}                                    │
│     → Extract: full description, salary, skills, experience, apply_url     │
│     → Extract OR lookup: company_website (from apply_url or extra pass)   │
│                                                                            │
│  3. Domain Resolution (apply_url parsing + search pass)                    │
│     apply_url → extract domain (https://company.com/careers/...)           │
│     If no apply_url domain → Google search: "{company_name} official site" │
│     → Verify against known domains list → canonical domain stored        │
│                                                                            │
│  4. Dedup Check (pre-insert)                                               │
│     PK = (job_title, company_name, location)                               │
│     If exists → skip insert, log duplicate                                  │
│     If new → insert with full schema                                        │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Workstreams

### Workstream 1 — Scraping Engine (Scrapy + Playwright Hybrid)

**Scrapy for discovery/crawl:**
- Spider: `IndeedSearchSpider` — takes search query + location, discovers job listing pages
- Follows pagination (50 results per page), extracts `jobkey` from Indeed URL patterns
- Settings: `CONCURRENT_REQUESTS=4`, `DOWNLOAD_DELAY=2`, `AUTOTHROTTLE_ENABLED=True`
- Custom retry middleware for 403/429 responses — rotate proxy before retry

**Playwright for detail extraction:**
- `DetailSpider` — launches headless Chrome via `playwright-stealth` plugin
- Stealth settings: `webdriver` property removed, `navigator.platform` spoofed, random viewport
- Extracts full job description (indeed.com/rc/jobs?jobkey=...) where Scrapy HTML is JS-rendered
- Adaptive delay: random 3–8s between requests to mimic human browsing
- Session management: new browser context per proxy rotation cycle

**Tech stack choice:**
```
Scrapy for: URL discovery, pagination, breadth-first crawl
Playwright for: JS-rendered detail pages, form interactions, stealth headless
PostgreSQL for: structured job data, deduplication via unique constraint
MongoDB alt: flexible schema if job fields vary widely (use pymongo)
```

### Workstream 2 — Proxy Rotation System

**Proxy providers (tiered fallback):**
1. **ScraperAPI** (`scraperapi.com`) — $29/month starter, auto-retries, JS rendering option
2. **ProxyMesh** (`proxymesh.com`) — $29/month, sticky sessions, global proxy pool
3. **Free proxies** (crawlera/smartproxy free tier) — fallback only

**ProxyPool class:**
```python
class ProxyPool:
    def __init__(self, providers: list[ProxyProvider]):
        self.providers = providers  # tried in priority order

    def get_proxy(self) -> str:
        # Returns: http://user:pass@proxy:port

    def report_failure(self, proxy: str, status_code: int):
        # Blacklists proxy for N minutes on 403/429
        # Escalates to next provider on consecutive failures
```

**Rotation strategy:**
- **Batch rotation:** Use proxy_1 for 10 requests, then rotate to proxy_2
- **Failure rotation:** Immediate rotate on HTTP 403/429/captcha
- **Session rotation:** New proxy per Playwright browser context (fresh TLS session)
- **Global proxy list file:** `proxies.txt` — one `host:port:user:pass` per line, reloads on SIGHUP

**Anti-blocking measures (layered):**
| Layer | Technique |
|-------|-----------|
| Request headers | `User-Agent` rotation (10+ real UA strings), Accept-Language, Accept-Encoding |
| Rate limiting | 1 request/3s on discovery, 1 request/5s on detail pages |
| Session isolation | Fresh cookie jar per proxy rotation cycle |
| CAPTCHA handling | 2captcha/Anti-Captcha API integration (optional, if budget allows) |
| JS fingerprint | playwright-stealth plugin — removes automation signals |
| Behavioral | Random scroll on detail page, random mouse movement via Playwright |

### Workstream 3 — Data Model (PostgreSQL Primary)

**PostgreSQL schema:**
```sql
-- Core jobs table
CREATE TABLE jobs (
    id            BIGSERIAL PRIMARY KEY,
    job_title     VARCHAR(500) NOT NULL,
    company_name  VARCHAR(300) NOT NULL,
    company_domain VARCHAR(255),           -- resolved canonical domain
    job_url       VARCHAR(1000) UNIQUE,   -- indeed.com unique job key URL
    apply_url     VARCHAR(1000),
    description   TEXT,
    salary_range  VARCHAR(200),
    skills        TEXT[],                 -- PostgreSQL array
    experience    VARCHAR(200),
    location      VARCHAR(300),
    posted_date   DATE,
    scraped_at    TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_job_identity UNIQUE (job_title, company_name, location)
);

-- Indexes for deduplication and querying
CREATE INDEX idx_jobs_company ON jobs(company_name);
CREATE INDEX idx_jobs_location ON jobs(location);
CREATE INDEX idx_jobs_posted ON jobs(posted_date);
CREATE INDEX idx_jobs_scraped ON jobs(scraped_at);

-- Change tracking for incremental runs
CREATE TABLE scrape_watermark (
    scrape_type   VARCHAR(50) PRIMARY KEY,  -- 'search' | 'detail'
    last_key      VARCHAR(255),
    last_scraped  TIMESTAMP
);

-- Proxy performance log (for adaptive rotation)
CREATE TABLE proxy_metrics (
    proxy         VARCHAR(255) PRIMARY KEY,
    success_count INT DEFAULT 0,
    fail_count    INT DEFAULT 0,
    avg_latency_ms INT,
    last_used     TIMESTAMP
);
```

**MongoDB alternative schema (if chosen):**
```javascript
// Collection: jobs
{
  _id: ObjectId,
  job_title: String,          // required — no misses
  company_name: String,       // required — no misses
  company_domain: String,      // resolved canonical domain
  job_url: String,             // unique index
  apply_url: String,
  description: String,
  salary_range: String,
  skills: [String],
  experience: String,
  location: String,
  posted_date: Date,
  scraped_at: Date
}

// Unique compound index for dedup
db.jobs.createIndex(
  { job_title: 1, company_name: 1, location: 1 },
  { unique: true }
)
```

### Workstream 4 — Company Domain Resolution

**Primary method: Apply URL parsing**
```
apply_url = https://careers.google.com/jobs/12345
→ parsed_domain = careers.google.com
→ canonical = google.com
```
Edge cases:
- `apply.indeed.com/cl/apply/` → extract from redirect chain
- `https://www.linkedin.com/jobs/view/...` → linkedin.com → extract company from path
- `https://firm.name.atsserver.com/...` → domain too obscure, mark as "pending_research"

**Fallback: Search-based domain lookup**
```
Given: company_name = "Acme Robotics Inc"
Search: "Acme Robotics Inc official site"
Parse: first organic result domain
Verify: compare against known domain aliases (e.g., "acme.com", "acmerobotics.com")
```
Implementation: Uses Google Custom Search API (free tier: 100 queries/day) or SerpAPI ($50/month). Falls back to DuckDuckGo HTML scrape with proxy rotation.

**Domain alias table:**
```
acme_corp → acme.com
acme inc  → acme.com
acme robotics → acmerobotics.com
```
Keeps resolved domain consistent even if company has multiple hiring pages.

### Workstream 5 — Hourly Auto-Refresh Scheduler

**APScheduler (AsyncIO-compatible):**
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
scheduler.add_job(
    run_scraper,
    'interval',
    hours=1,
    args=[spider_name, search_queries],
    id='indeed_hourly_scrape',
    replace_existing=True,
)
scheduler.start()
```

**Docker Compose cron alternative:**
```yaml
# Run scraper on schedule without Python scheduler
cron:
  image: indeed-scraper:latest
  command: python -m scrapy runspider indeed_spider.py -a run_mode=scheduled
  environment:
    SCRAPE_INTERVAL_HOURS: "1"
  entrypoint: /bin/bash -c "while true; do python run.py; sleep 3600; done"
```

**Watermark-based incremental scrape (no full reload):**
- Store `last_jobkey` per search query in `scrape_watermark` table
- On each run: only process jobs with `jobkey > last_jobkey`
- Full re-scrape option via `--full` flag (overrides watermark)

### Workstream 6 — Deployment & Operations

**Local dev (Docker Compose):**
```bash
git clone https://github.com/9KMan/JOB-20260524095349-000049.git
cd JOB-20260524095349-000049
cp .env.example .env  # add PROXYMESH_KEY, SCRAPERAPI_KEY
docker-compose up -d
docker-compose logs -f scraper  # watch real-time scraping
```

**Required environment variables:**
```
INDEED_BASE_URL=https://www.indeed.com
SEARCH_QUERIES=python developer;data engineer;machine learning
LOCATIONS=Remote;New York, NY;San Francisco, CA
DB_TYPE=postgres  # or 'mongodb'
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=indeed_scraper
POSTGRES_USER=scraper
POSTGRES_PASSWORD=<secret>
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=indeed_scraper
PROXYMESH_USER=<user>
PROXYMESH_PASS=<pass>
SCRAPERAPI_KEY=<key>
GOOGLE_SEARCH_KEY=<key>  # optional
SCHEDULE_INTERVAL_HOURS=1
LOG_LEVEL=INFO
```

**Docker Compose services:**
| Service | Image | Purpose |
|---------|-------|---------|
| scraper | indeed-scraper:latest | Main scraping process |
| postgres | postgres:15-alpine | Job storage |
| redis | redis:7-alpine | Job queue (if usingRQ) |
| prometheus | prom/prometheus:latest | Metrics collection |
| grafana | grafana/grafana:latest | Dashboards |

**GitHub Actions CI/CD:**
```yaml
# .github/workflows/scrape.yml
on: [push, schedule: cron: '0 * * * *']  # hourly
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Test scraping (staging)
        run: docker-compose up --abort-on-container-exit
      - name: Push to ECR
        run: ./scripts/ecr-push.sh
```

---

## 4. API Design

### Internal Scraping API (for scheduler + monitoring)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/jobs` | List jobs with pagination, filters |
| GET | `/api/jobs/{job_url}` | Get single job by URL |
| GET | `/api/jobs/count` | Total job count, dup ratio |
| GET | `/api/proxies` | List proxy pool status |
| POST | `/api/proxies/rotate` | Force proxy rotation |
| GET | `/api/watermarks` | Current scrape watermarks |
| POST | `/api/scrape/trigger` | Manual scrape trigger |
| GET | `/api/health` | Health check (no auth) |

### REST API Endpoints (FastAPI)

```python
# jobs router
@app.get("/jobs")
def list_jobs(
    skip: int = 0,
    limit: int = 50,
    company: str = None,
    location: str = None,
    posted_within_days: int = 7,
):
    """List jobs with optional filters."""

@app.get("/jobs/{job_url:path}")
def get_job(job_url: str):
    """Get job by URL (URL-encoded)."""

@app.get("/jobs/stats/summary")
def job_stats():
    """Aggregate stats: total, dups caught, by company, by location."""

# health
@app.get("/health")
def health_check():
    return {"status": "ok", "db": "connected", "proxies": "alive"}
```

---

## 5. Technical Decisions

1. **Scrapy + Playwright hybrid over single framework** — Scrapy handles breadth-first crawl efficiently; Playwright handles JS-rendered detail pages. Neither alone covers the full stack.
2. **Proxy rotation as first-class citizen** — `ProxyPool` is a standalone component, not buried in middleware. Easy to swap providers, add new ones, and monitor metrics.
3. **PostgreSQL over MongoDB (default)** — Structured schema with `UNIQUE` constraint on `(job_title, company_name, location)` catches duplicates at DB level. MongoDB alternative provided but Postgres is primary.
4. **Watermark-based incremental scrape** — Store `last_jobkey` per query; only process new listings. Avoids re-scraping entire search on every hourly run.
5. **Domain resolution via apply URL (primary) + Google search (fallback)** — apply URL is always available on Indeed detail pages; parsing it is fast and free. Only triggers expensive search pass when apply URL is a generic ATS.
6. **Docker Compose for local dev + production parity** — Same images run locally and in CI/CD. No "works on my machine" divergence.
7. **playwright-stealth over raw Playwright** — Stealth plugin removes automation signals (webdriver, navigator flags) that Indeed uses to detect bots. Worth the additional dependency.
8. **APScheduler over cron at container level** — Allows cron expression flexibility (`0 * * * *`), integration with job queue, and in-process health monitoring.
9. **Adaptive delay (random 3–8s) over fixed delay** — Fixed delays are easy to fingerprint. Random within a human-like range reduces detection probability.
10. **GitHub Actions hourly schedule over external cron** — Keeps credentials (proxy keys) in-repo secrets, no external cron service needed.

---

## 6. Out of Scope

- Indeed account authentication (session-based scraping only — no login required)
- CAPTCHA solving as primary flow (integrate as fallback only, adds latency and cost)
- Real-time streaming (micro-batch hourly refresh, not sub-minute)
- ML-based job categorization or salary parsing (structured extraction only)
- Mobile app development
- Job application submission (scraping only, no Apply click automation)
- Multi-language Indeed sites (indeed.com English only)

---

## 7. Success Metrics

- **Uptime:** Scraper completes hourly runs for 7+ consecutive days without manual intervention
- **Data completeness:** job_title and company_name extracted on 100% of processed listings
- **Error rate:** <5% HTTP errors (403/429/captcha) that cause skips per run
- **Duplicate catch:** All exact `(job_title, company_name, location)` dups caught at insert time
- **Domain resolution:** >90% of jobs end with a valid `company_domain` (resolved or pending_research)
- **Latency:** Single hourly full-scrape run completes within 45 minutes for 5 search queries × 5 pages each
- **Proxy health:** No single proxy flagged as blocked for >3 consecutive attempts