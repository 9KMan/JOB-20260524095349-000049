"""Playwright-based detail extractor with stealth configuration."""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Optional

from playwright.async_api import AsyncPlaywright, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

# Realistic user agent strings
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def get_random_viewport() -> dict:
    widths = [1920, 1680, 1440, 1536, 1280]
    heights = [1080, 1050, 900, 960, 720]
    return {"width": random.choice(widths), "height": random.choice(heights)}


class PlaywrightDetailExtractor:
    """Headless Chrome extraction with stealth configuration."""

    def __init__(self, proxy: Optional[str] = None, batch_size: int = 10):
        self.proxy = proxy
        self.batch_size = batch_size
        self._playwright: Optional[Playwright] = None
        self._browser = None
        self._context: Optional[BrowserContext] = None
        self._request_count = 0

    async def initialize(self):
        """Initialize Playwright with stealth settings."""
        self._playwright = await AsyncPlaywright().start()

        # Launch headless Chrome with stealth arguments
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-service-autorun",
            "--password-store=basic",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]

        if self.proxy:
            launch_args.append(f"--proxy-server={self.proxy}")

        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=launch_args,
        )

        await self._create_fresh_context()

    async def _create_fresh_context(self):
        """Create a new browser context with fresh cookies."""
        if self._context:
            await self._context.close()

        viewport = get_random_viewport()
        self._context = await self._browser.new_context(
            viewport=viewport,
            user_agent=get_random_user_agent(),
            locale="en-US",
            timezone="America/New_York",
            geolocation={"latitude": 40.7128, "longitude": -74.0060},
            permissions=["geolocation"],
        )

        # Set extra HTTP headers
        await self._context.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        })

        self._request_count = 0

    async def extract_job_details(self, url: str) -> Optional[dict]:
        """Extract full job details from a detail page."""
        if not self._context:
            await self.initialize()

        # Rotate context if batch size reached
        self._request_count += 1
        if self._request_count >= self.batch_size:
            await self._create_fresh_context()

        page = await self._context.new_page()

        try:
            # Navigate with timeout
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Random delay to mimic human behavior
            await self._human_delay()

            # Scroll to load lazy content
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(random.uniform(1, 2))
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(1, 2))

            # Extract job data
            job_data = await self._extract_from_page(page)
            return job_data

        except Exception as e:
            logger.error(f"Failed to extract {url}: {e}")
            return None
        finally:
            await page.close()

    async def _extract_from_page(self, page: Page) -> dict:
        """Extract job details from the loaded page."""
        # Wait for main content to be visible
        await page.wait_for_selector("[data-testid='job-detail-description']", timeout=10000)

        # Extract job title
        title_elem = await page.query_selector("h1[data-testid='job-title'], h1.jobTitle, h2.jobsearch-JobInfoHeader-title")
        job_title = await title_elem.inner_text() if title_elem else None

        # Extract company name
        company_elem = await page.query_selector(
            "div[data-testid='job-info-company-name'], "
            "a[data-testid='job-info-company-name'], "
            ".company_location .companyName"
        )
        company_name = await company_elem.inner_text() if company_elem else None

        # Extract location
        location_elem = await page.query_selector(
            "div[data-testid='job-info-location'], "
            "div[data-testid='jobLocation']"
        )
        location = await location_elem.inner_text() if location_elem else None

        # Extract salary
        salary_elem = await page.query_selector(
            "span[data-testid='salary-info'], "
            "span.salary-snippet, "
            "#salaryInfo"
        )
        salary_range = await salary_elem.inner_text() if salary_elem else None

        # Extract posted date
        date_elem = await page.query_selector(
            "span[data-testid='job-age'], "
            "span.date"
        )
        posted_date_str = await date_elem.inner_text() if date_elem else None

        # Extract job description
        desc_elem = await page.query_selector(
            "[data-testid='job-detail-description'], "
            "#jobDescriptionText"
        )
        description = await desc_elem.inner_text() if desc_elem else None

        # Extract skills (from tags/badges in description)
        skills = []
        skill_elems = await page.query_selector_all(
            ".job-snippet ul li, "
            "[data-testid='skills'] span, "
            ".resume-snippet ul li"
        )
        for skill_elem in skill_elems:
            skill_text = await skill_elem.inner_text()
            if skill_text:
                skills.append(skill_text.strip())

        # Extract experience level
        exp_elem = await page.query_selector(
            "[data-testid='experience-level'], "
            ".experience-level"
        )
        experience = await exp_elem.inner_text() if exp_elem else None

        # Extract apply URL
        apply_elem = await page.query_selector(
            "a[data-testid='apply-button'], "
            ".indeed_apply_button, "
            "#applyButton a"
        )
        apply_url = await apply_elem.get_attribute("href") if apply_elem else None
        if apply_url and not apply_url.startswith("http"):
            apply_url = f"https://www.indeed.com{apply_url}"

        return {
            "job_title": job_title.strip() if job_title else None,
            "company_name": company_name.strip() if company_name else None,
            "location": location.strip() if location else None,
            "salary_range": salary_range.strip() if salary_range else None,
            "description": description,
            "skills": skills,
            "experience": experience.strip() if experience else None,
            "apply_url": apply_url,
            "posted_date": self._parse_date(posted_date_str),
        }

    @staticmethod
    def _parse_date(date_str: str | None) -> str | None:
        """Parse Indeed date string to YYYY-MM-DD format."""
        if not date_str:
            return None

        date_str = date_str.strip().lower()

        if "today" in date_str or "just posted" in date_str:
            import datetime
            return str(datetime.date.today())
        elif "days ago" in date_str:
            match = re.search(r'(\d+)', date_str)
            if match:
                import datetime
                days = int(match.group(1))
                return str(datetime.date.today() - datetime.timedelta(days=days))
        elif "weeks ago" in date_str:
            match = re.search(r'(\d+)', date_str)
            if match:
                import datetime
                weeks = int(match.group(1))
                return str(datetime.date.today() - datetime.timedelta(weeks=weeks))

        return None

    async def _human_delay(self):
        """Random delay to mimic human browsing behavior."""
        delay = random.uniform(3, 8)
        await asyncio.sleep(delay)

    async def close(self):
        """Clean up Playwright resources."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()