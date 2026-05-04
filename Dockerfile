FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# Install Python deps, then Playwright system deps + Chromium (runs as root in Docker)
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install-deps chromium && \
    playwright install chromium

COPY . .

CMD ["python", "main.py"]
