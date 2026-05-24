# Deployment Guide

## Indeed Job Scraper - Production Deployment

### Prerequisites
- Docker & Docker Compose
- PostgreSQL 15+ (or MongoDB for alternative)
- GitHub account for CI/CD
- ProxyMesh and/or ScraperAPI accounts

---

## Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/9KMan/JOB-20260524095349-000049.git
cd JOB-20260524095349-000049
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Start Services
```bash
docker-compose up -d
```

### 4. Verify
```bash
docker-compose logs -f scraper
docker-compose logs -f api
```

---

## Configuration

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `POSTGRES_PASSWORD` | PostgreSQL password | `secure_password` |
| `PROXYMESH_USER` | ProxyMesh username | `myuser` |
| `PROXYMESH_PASS` | ProxyMesh password | `mypassword` |
| `SCRAPERAPI_KEY` | ScraperAPI API key | `abc123` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_TYPE` | `postgres` | `postgres` or `mongodb` |
| `SEARCH_QUERIES` | See `.env.example` | Semicolon-separated search queries |
| `LOCATIONS` | See `.env.example` | Semicolon-separated locations |
| `SCHEDULE_INTERVAL_HOURS` | `1` | Hours between scrape cycles |
| `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR |

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/jobs` | List jobs with filters |
| GET | `/api/jobs/{job_url}` | Get job by URL |
| GET | `/api/jobs/count` | Job count stats |
| GET | `/api/proxies` | Proxy pool status |
| POST | `/api/proxies/rotate` | Force rotation |
| POST | `/api/scrape/trigger` | Manual trigger |

---

## Monitoring

- **API**: http://localhost:8000
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)

---

## Troubleshooting

### Scraper not finding jobs
1. Check proxy configuration
2. Verify User-Agent rotation
3. Review logs: `docker-compose logs scraper`

### Database connection errors
1. Verify PostgreSQL is running
2. Check `POSTGRES_PASSWORD` in `.env`
3. Ensure port 5432 is accessible

### High error rate
1. Check proxy health: `GET /api/proxies`
2. Rotate proxies: `POST /api/proxies/rotate`
3. Reduce `CONCURRENT_REQUESTS` in spider settings

---

## Scaling

### Multiple Scraper Instances
```yaml
scraper:
  replicas: 3
  # Use Redis queue for job distribution
```

### Horizontal Scaling
```bash
# Add more proxy providers in ProxyPool
# Increase CONCURRENT_REQUESTS in Scrapy settings
```

---

## Maintenance

### Log Rotation
```bash
# Add to docker-compose.yml
logging:
  options:
    max-size: "10m"
    max-file: "3"
```

### Database Backups
```bash
# PostgreSQL
docker-compose exec postgres pg_dump -U scraper indeed_scraper > backup.sql

# MongoDB
docker-compose exec mongo mongodump --archive > backup.archive
```