FROM python:3.11-slim

# wget + ca-certificates are needed by playwright install --with-deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium and its OS-level dependencies in one step
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "main.py"]
