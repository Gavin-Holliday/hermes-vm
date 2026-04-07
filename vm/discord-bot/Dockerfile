FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source into /app/discord_bot/ so flat imports (from history import X) resolve correctly
COPY . ./discord_bot/

WORKDIR /app/discord_bot

CMD ["python", "bot.py"]
