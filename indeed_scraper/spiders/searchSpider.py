"""Scrapy spider for Indeed job search discovery."""
from __future__ import annotations

import logging
import re
from typing import Iterable, Iterator

import scrapy
from scrapy.http import Request, Response

logger = logging.getLogger(__name__)


class IndeedSearchSpider(scrapy.Spider):
    """Spider for discovering job listings via Indeed search."""

    name = "indeed_search"
    custom_settings = {
        "CONCURRENT_REQUESTS": 4,
        "DOWNLOAD_DELAY": 2,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 1,
        "AUTOTHROTTLE_MAX_DELAY": 5,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 3,
        "DOWNLOADER_MIDDLEWARES": {
            "indeed_scraper.middlewares.ProxyRotationMiddleware": 100,
            "indeed_scraper.middlewares.UserAgentMiddleware": 200,
        },
        "SPIDER_MIDDLEWARES": {
            "indeed_scraper.middlewares.StealthMiddleware": 300,
        },
    }

    def __init__(self, queries: list[str], locations: list[str], base_url: str = "https://www.indeed.com"):
        super().__init__()
        self.queries = queries
        self.locations = locations
        self.base_url = base_url
        self._processed_keys: set[str] = set()

    def start_requests(self) -> Iterable[Request]:
        """Generate initial search requests for all query + location combinations."""
        for query in self.queries:
            for location in self.locations:
                search_url = (
                    f"{self.base_url}/jobs?q={query}&l={location}"
                    "&filter=0"  # Keep all results
                )
                yield Request(
                    search_url,
                    callback=self.parse_search_page,
                    meta={"query": query, "location": location, "page": 0},
                )

    def parse_search_page(self, response: Response) -> Iterator[Request]:
        """Parse search results page and extract job listings."""
        query = response.meta["query"]
        location = response.meta["location"]
        page = response.meta["page"]

        logger.info(f"Parsing search page {page} for query='{query}', location='{location}'")

        # Extract job keys from job cards
        job_keys = self._extract_job_keys(response)

        for job_key in job_keys:
            if job_key not in self._processed_keys:
                self._processed_keys.add(job_key)
                detail_url = f"{self.base_url}/rc/jobs?jobkey={job_key}"
                yield Request(
                    detail_url,
                    callback=self.parse_job_detail,
                    meta={"job_key": job_key, "query": query, "location": location},
                    dont_filter=True,
                )

        # Follow pagination
        next_page = self._get_next_page(response)
        if next_page:
            yield Request(
                next_page,
                callback=self.parse_search_page,
                meta={"query": query, "location": location, "page": page + 1},
            )

    def _extract_job_keys(self, response: Response) -> list[str]:
        """Extract unique job keys from search results."""
        # Indeed job keys are in URLs like /rc/jobs?jobkey=abc123
        # and in data-jobkey attributes
        keys = set()

        # Pattern 1: jobkey in URL
        patterns = [
            r'/rc/jobs\?jobkey=([a-zA-Z0-9]+)',
            r'data-jobkey="([a-zA-Z0-9]+)"',
            r'jobkeys[]=([a-zA-Z0-9]+)',
        ]

        text = response.text
        for pattern in patterns:
            matches = re.findall(pattern, text)
            keys.update(matches)

        return list(keys)

    def _get_next_page(self, response: Response) -> str | None:
        """Get the next pagination URL if available."""
        # Look for pagination link
        next_link = response.css("a[data-testid='pagination-page-next']::attr(href)").get()
        if not next_link:
            next_link = response.css("div[data-testid='pagination'] a:last-child::attr(href)").get()
        if not next_link:
            # Try generic pattern
            next_link = response.css("a[aria-label='Next']::attr(href)").get()

        if next_link:
            return response.urljoin(next_link)
        return None

    def parse_job_detail(self, response: Response) -> dict:
        """Extract job details from detail page (used as fallback when Playwright fails)."""
        job_key = response.meta["job_key"]

        # Extract basic info from HTML (partial - full extraction via Playwright)
        title = response.css("h1[data-testid='job-title']::text").get()
        if not title:
            title = response.css("h1.jobTitle::text").get()
            if not title:
                title = response.css("h2.jobsearch-JobInfoHeader-title::text").get()

        company = response.css("div[data-testid='job-info-company-name']::text").get()
        if not company:
            company = response.css("div.company_location .companyName::text").get()
            if not company:
                company = response.css("a[data-testid='job-info-company-name']::text").get()

        location = response.css("div[data-testid='job-info-location']::text").get()
        if not location:
            location = response.css("div[data-testid='jobLocation']::text").get()

        salary = response.css("span[data-testid='salary-info']::text").get()
        if not salary:
            salary = response.css("span.salary-snippet::text").get()

        # Extract apply URL
        apply_url = response.css("a[data-testid='apply-button']::attr(href)").get()
        if not apply_url:
            apply_url = response.css("a.indeed_apply_button::attr(href)").get()

        # Extract posted date
        posted_date = response.css("span[data-testid='job-age']::text").get()
        if not posted_date:
            posted_date = response.css("span.date::text").get()

        return {
            "job_key": job_key,
            "job_title": title.strip() if title else None,
            "company_name": company.strip() if company else None,
            "location": location.strip() if location else None,
            "salary_range": salary.strip() if salary else None,
            "apply_url": apply_url,
            "posted_date": self._parse_date(posted_date),
            "job_url": response.url,
        }

    def _parse_date(self, date_str: str | None) -> str | None:
        """Parse Indeed date string to YYYY-MM-DD format."""
        if not date_str:
            return None

        # Indeed date formats: "30 days ago", "Today", "Just posted", "2 weeks ago"
        date_str = date_str.strip().lower()

        if "today" in date_str or "just posted" in date_str:
            import datetime
            return str(datetime.date.today())
        elif "days ago" in date_str:
            import re
            match = re.search(r'(\d+)', date_str)
            if match:
                import datetime
                days = int(match.group(1))
                return str(datetime.date.today() - datetime.timedelta(days=days))
        elif "weeks ago" in date_str:
            import re
            match = re.search(r'(\d+)', date_str)
            if match:
                import datetime
                weeks = int(match.group(1))
                return str(datetime.date.today() - datetime.timedelta(weeks=weeks))

        return None

    @staticmethod
    def closed(spider):
        logger.info(f"Spider {spider.name} closed. Processed {len(spider._processed_keys)} unique jobs.")