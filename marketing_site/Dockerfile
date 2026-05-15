FROM python:3.11-slim

WORKDIR /app

# Set timezone to Israel
ENV TZ=Asia/Jerusalem
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install only what we need (no gcc needed if using binary wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev curl netcat-openbsd && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENV PYTHONPATH=/app

CMD ["/app/entrypoint.sh"]
