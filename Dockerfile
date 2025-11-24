FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml .
COPY keilog/ ./keilog/
COPY keiconf_broute.py .
COPY src/ ./src/
COPY config/ ./config/

# Install dependencies using uv
RUN uv pip install --system --no-cache -r pyproject.toml

# Create logs directory
RUN mkdir -p /app/logs

# Run the smartmeter logger
CMD ["python", "-u", "src/smartmeter_logger.py"]
