FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg unzip fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y chromium chromium-driver



WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV CHROMEDRIVER_PATH="/usr/bin/chromedriver"
ENV CHROME_BIN="/usr/bin/chromium"
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
