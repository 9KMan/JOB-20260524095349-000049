"""Unit tests for the Indeed Job Scraper."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from indeed_scraper.config import Settings
from indeed_scraper.domainResolver import DomainResolver, extract_domain_from_url, normalize_domain
from indeed_scraper.utils import parse_indeed_date, sanitize_string, is_valid_url


class TestDomainResolver:
    """Tests for domain resolution."""

    def test_extract_domain_from_apply_url(self):
        """Test domain extraction from apply URLs."""
        assert extract_domain_from_url("https://careers.google.com/jobs/12345") == "careers.google.com"
        assert extract_domain_from_url("https://jobs.microsoft.com/position/456") == "jobs.microsoft.com"
        assert extract_domain_from_url("https://www.linkedin.com/jobs/view/789") == "linkedin.com"

    def test_normalize_domain(self):
        """Test domain normalization."""
        assert normalize_domain("careers.google.com") == "google.com"
        assert normalize_domain("jobs.amazon.com") == "amazon.com"
        assert normalize_domain("www.apple.com") == "apple.com"

    def test_resolve_from_apply_url(self):
        """Test primary resolution via apply URL."""
        resolver = DomainResolver()
        domain = resolver.resolve_from_apply_url("https://careers.google.com/jobs/12345")
        assert domain == "google.com"

    def test_pending_research_for_unknown(self):
        """Test that unknown companies are marked pending."""
        resolver = DomainResolver()
        domain = resolver.get_canonical_domain("Unknown Company XYZ", None)
        assert domain == "pending_research"


class TestDateParsing:
    """Tests for date parsing utilities."""

    def test_parse_today(self):
        """Test parsing 'today' date."""
        result = parse_indeed_date("Today")
        assert result is not None

    def test_parse_days_ago(self):
        """Test parsing 'X days ago' date."""
        result = parse_indeed_date("5 days ago")
        assert result is not None

    def test_parse_weeks_ago(self):
        """Test parsing 'X weeks ago' date."""
        result = parse_indeed_date("2 weeks ago")
        assert result is not None

    def test_parse_invalid(self):
        """Test parsing invalid date."""
        assert parse_indeed_date(None) is None
        assert parse_indeed_date("") is None


class TestStringUtils:
    """Tests for string utility functions."""

    def test_sanitize_whitespace(self):
        """Test whitespace sanitization."""
        assert sanitize_string("  hello   world  ") == "hello world"
        assert sanitize_string("\t\ntest\t\n") == "test"

    def test_sanitize_none(self):
        """Test sanitizing None."""
        assert sanitize_string(None) is None


class TestURLValidation:
    """Tests for URL validation."""

    def test_valid_urls(self):
        """Test valid URL detection."""
        assert is_valid_url("https://www.example.com")
        assert is_valid_url("http://careers.google.com/jobs/123")
        assert is_valid_url("https://jobs.microsoft.com/position/456?ref=789")

    def test_invalid_urls(self):
        """Test invalid URL detection."""
        assert not is_valid_url(None)
        assert not is_valid_url("")
        assert not is_valid_url("not a url")
        assert not is_valid_url("ftp://invalid.com")


class TestSettings:
    """Tests for configuration settings."""

    def test_settings_defaults(self):
        """Test default values are set."""
        # This will fail if env vars aren't set, which is expected
        with pytest.raises(ValueError):
            _ = Settings()


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = MagicMock()
    settings.SEARCH_QUERIES = "python developer;data engineer"
    settings.LOCATIONS = "Remote;New York, NY"
    settings.SCHEDULE_INTERVAL_HOURS = 1
    settings.DB_TYPE = "postgres"
    settings.POSTGRES_HOST = "localhost"
    settings.POSTGRES_PORT = 5432
    settings.POSTGRES_DB = "test_db"
    settings.POSTGRES_USER = "test_user"
    settings.POSTGRES_PASSWORD = "test_pass"
    return settings