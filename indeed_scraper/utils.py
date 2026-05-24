"""Utility functions and helpers."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def parse_indeed_date(date_str: Optional[str]) -> Optional[str]:
    """Parse Indeed date strings into ISO format."""
    if not date_str:
        return None

    date_str = date_str.strip().lower()

    # Handle various Indeed date formats
    if "today" in date_str or "just posted" in date_str:
        return str(datetime.now().date())

    if "days ago" in date_str:
        match = re.search(r'(\d+)', date_str)
        if match:
            days = int(match.group(1))
            return str((datetime.now() - timedelta(days=days)).date())

    if "weeks ago" in date_str:
        match = re.search(r'(\d+)', date_str)
        if match:
            weeks = int(match.group(1))
            return str((datetime.now() - timedelta(weeks=weeks)).date())

    if "month" in date_str:
        match = re.search(r'(\d+)', date_str)
        if match:
            months = int(match.group(1))
            return str((datetime.now() - timedelta(days=months * 30)).date())

    return None


def sanitize_string(text: Optional[str]) -> Optional[str]:
    """Clean and sanitize text content."""
    if not text:
        return None

    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_salary_range(salary_text: Optional[str]) -> Optional[str]:
    """Extract and normalize salary range from text."""
    if not salary_text:
        return None

    # Common patterns: "$50,000 - $70,000 a year", "$60/hour"
    match = re.search(r'\$[\d,]+(?:\s*-\s*\$[\d,]+)?', salary_text)
    if match:
        return match.group(0)

    return salary_text.strip() if salary_text else None


def is_valid_url(url: Optional[str]) -> bool:
    """Check if string is a valid URL."""
    if not url:
        return False

    pattern = r'^https?://[\w\-\.]+(?:\.[a-z]{2,})+(?:/[\w\-\./?%&=]*)?$'
    return bool(re.match(pattern, url))


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        return f"{seconds / 3600:.1f}h"