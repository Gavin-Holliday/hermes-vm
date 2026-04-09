FROM python:3.12-slim

WORKDIR /app

# ffmpeg required for discord.py[voice] audio playback
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source into /app/discord_bot/ so package imports resolve correctly
COPY . ./discord_bot/

WORKDIR /app/discord_bot

EXPOSE 8001

CMD ["python", "bot.py"]
