# ThetaGuard Production Container Image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PUBLIC_READ_ONLY_MODE=true \
    ALPACA_PAPER_TRADE=true \
    ENABLE_TRADING_DAEMON=true

WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Ensure data and logs directories exist
RUN mkdir -p data logs

# Expose default port
EXPOSE 8000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Start FastAPI application — uses Python's os.getenv("PORT") for platform-agnostic
# port binding. Shell expansion (${PORT}) is unreliable on Railway/some container runtimes.
CMD ["python", "-m", "src.api.main"]
