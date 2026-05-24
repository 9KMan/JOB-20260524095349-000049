FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright browsers
RUN pip install playwright && playwright install chromium --with-deps

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY indeed_scraper/ ./indeed_scraper/

# Set up environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default command (scheduled mode)
CMD ["python", "-m", "indeed_scraper.run", "--mode", "scheduled"]

# Alternative: run once
# CMD ["python", "-m", "indeed_scraper.run", "--mode", "once"]