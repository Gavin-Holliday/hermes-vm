FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    clamav clamav-daemon \
    && rm -rf /var/lib/apt/lists/* \
    && freshclam --quiet || true

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./proxy/
RUN mkdir -p /app/workspace /app/data /app/data/research
EXPOSE 8000
ENV SYSTEM_PROMPT_FILE=/app/proxy/system_prompt.txt
CMD ["uvicorn", "proxy.main:app", "--host", "0.0.0.0", "--port", "8000"]
