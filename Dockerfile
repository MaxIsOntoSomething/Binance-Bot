FROM python:3.9-slim

# Add metadata labels
LABEL maintainer="maskiplays"
LABEL description="Binance Trading Bot with multiple price drop thresholds"
LABEL version="1.0"

# Create non-root user
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Set working directory
WORKDIR /app

# Install system dependencies and cleanup in same layer
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Set ownership to non-root user
RUN chown -R botuser:botuser /app

# Switch to non-root user
USER botuser

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

# Define environment variables
ENV NAME=BinanceBot \
    DOCKER_CONTAINER=yes \
    PYTHONUNBUFFERED=1

EXPOSE 80

CMD ["python", "main.py"]