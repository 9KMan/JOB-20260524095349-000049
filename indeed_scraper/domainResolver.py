"""Domain resolution service for company websites."""
from typing import Optional

import logging
import re
from typing import Optional

from indeed_scraper.config import settings

logger = logging.getLogger(__name__)


# Known company domain aliases for disambiguation
COMPANY_ALIASES = {
    "google": "google.com",
    "alphabet": "google.com",
    "meta": "meta.com",
    "facebook": "facebook.com",
    "amazon": "amazon.com",
    "apple": "apple.com",
    "microsoft": "microsoft.com",
    "netflix": "netflix.com",
    "linkedin": "linkedin.com",
    "twitter": "twitter.com",
    "x corp": "x.com",
}


def extract_domain_from_url(url: str) -> Optional[str]:
    """Extract and normalize domain from a URL."""
    if not url:
        return None

    try:
        # Handle special Indeed apply URLs
        if "apply.indeed.com" in url:
            # Extract the redirect target from Indeed's apply URL
            match = re.search(r'url=([^&]+)', url)
            if match:
                url = match.group(1)

        # Handle LinkedIn URLs
        if "linkedin.com" in url:
            # Extract company from LinkedIn job path
            match = re.search(r'linkedin\.com/jobs/(\d+)', url)
            if match:
                return "linkedin.com"

        # Parse URL
        match = re.search(r'https?://(?:www\.)?([^/]+)', url)
        if match:
            domain = match.group(1).lower()

            # Normalize common subdomains
            if domain.startswith("careers."):
                domain = domain.replace("careers.", "")
            elif domain.startswith("jobs."):
                domain = domain.replace("jobs.", "")
            elif domain.startswith("apply."):
                domain = domain.replace("apply.", "")

            return domain

    except Exception as e:
        logger.error(f"Failed to parse URL '{url}': {e}")

    return None


def normalize_domain(domain: str) -> str:
    """Normalize a domain to its canonical form."""
    if not domain:
        return ""

    domain = domain.lower().strip()

    # Check aliases
    for alias, canonical in COMPANY_ALIASES.items():
        if alias in domain:
            return canonical

    # Remove common prefixes
    for prefix in ["careers.", "jobs.", "www.", "apply.", "hire.", "talent."]:
        if domain.startswith(prefix):
            domain = domain[len(prefix):]

    return domain


def get_top_level_domain(domain: str) -> str:
    """Extract the top-level domain from a full domain."""
    parts = domain.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain


class DomainResolver:
    """Service for resolving company domains from job listings."""

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._pending: dict[str, str] = {}  # company_name -> status

    def resolve_from_apply_url(self, apply_url: str) -> Optional[str]:
        """Primary resolution: extract domain from apply URL."""
        if not apply_url:
            return None

        # Check cache first
        if apply_url in self._cache:
            return self._cache[apply_url]

        domain = extract_domain_from_url(apply_url)
        if domain and self._is_valid_company_domain(domain):
            self._cache[apply_url] = domain
            return domain

        return None

    def resolve_from_company_name(self, company_name: str) -> Optional[str]:
        """Fallback resolution: search for company website."""
        if not company_name:
            return None

        # Check cache
        if company_name in self._cache:
            return self._cache[company_name]

        # Check aliases
        normalized = company_name.lower().strip()
        if normalized in COMPANY_ALIASES:
            domain = COMPANY_ALIASES[normalized]
            self._cache[company_name] = domain
            return domain

        # Mark as pending research (would use Google Search API in production)
        self._pending[company_name] = "pending_research"

        return None

    def _is_valid_company_domain(self, domain: str) -> bool:
        """Check if domain is a valid company domain (not ATS, not generic)."""
        if not domain:
            return False

        # Reject generic/ATS domains
        invalid_domains = [
            "indeed.com",
            "linkedin.com",
            "glassdoor.com",
            "ziprecruiter.com",
            "greenhouse.io",
            "lever.co",
            "workday.com",
            "taleo.net",
            "successfactors.com",
            "icims.com",
            "jobvite.com",
            "smartrecruiters.com",
            "ashby.com",
        ]

        tld = get_top_level_domain(domain)

        # Reject if top-level domain is suspicious
        if tld in invalid_domains or domain in invalid_domains:
            return False

        # Reject very short or generic domains
        if len(domain) < 4:
            return False

        # Reject domains with numbers only
        if re.match(r'^\d+\.', domain):
            return False

        return True

    def get_canonical_domain(self, company_name: str, apply_url: Optional[str] = None) -> str:
        """Get canonical domain for a company, trying all methods."""
        # Method 1: Apply URL
        if apply_url:
            domain = self.resolve_from_apply_url(apply_url)
            if domain:
                return domain

        # Method 2: Company name lookup
        domain = self.resolve_from_company_name(company_name)
        if domain:
            return domain

        # Fallback: return pending status
        return "pending_research"

    def mark_research_complete(self, company_name: str, domain: str):
        """Mark a pending company as resolved."""
        self._cache[company_name] = domain
        if company_name in self._pending:
            del self._pending[company_name]
        logger.info(f"Resolved domain for '{company_name}': {domain}")

    def get_pending_companies(self) -> list[str]:
        """Get list of companies still pending domain research."""
        return list(self._pending.keys())

    def get_cache_stats(self) -> dict:
        """Return domain resolution statistics."""
        return {
            "cached": len(self._cache),
            "pending": len(self._pending),
            "total": len(self._cache) + len(self._pending),
        }