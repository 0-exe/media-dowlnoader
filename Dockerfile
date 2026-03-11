FROM python:3.12-slim

# Install system dependencies (ffmpeg for media processing, curl for healthcheck)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp binary
RUN curl -fsSL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
        -o /usr/local/bin/yt-dlp \
    && chmod +x /usr/local/bin/yt-dlp

WORKDIR /app

# Install Python dependencies (layer cached separately from app code)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Non-root user for security
RUN useradd --system --no-create-home appuser
USER appuser

ENV APP_PORT=8080
EXPOSE ${APP_PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${APP_PORT}/api/health || exit 1

CMD ["python", "app.py"]
