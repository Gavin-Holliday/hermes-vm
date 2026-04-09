FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy proxy package into /app/proxy/ so "from proxy.X import Y" works
COPY . ./proxy/

# Persistent dirs — mount volumes here in production
RUN mkdir -p /app/workspace /app/data

EXPOSE 8000

# system_prompt.txt ends up at /app/proxy/system_prompt.txt
ENV SYSTEM_PROMPT_FILE=/app/proxy/system_prompt.txt

CMD ["uvicorn", "proxy.main:app", "--host", "0.0.0.0", "--port", "8000"]
