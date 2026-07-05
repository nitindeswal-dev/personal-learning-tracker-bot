# HuggingFace Spaces — Docker SDK
# Builds an always-on container that runs the Telegram bot + a tiny HTTP
# keep-alive server. Free CPU tier, no credit card needed.
#
# Deploy:
#   1. Create a Space on https://huggingface.co/new-space  (SDK = Docker, blank template)
#   2. Push this repo to the Space's git remote
#   3. In Space Settings > Variables and secrets, add:
#        TELEGRAM_BOT_TOKEN  (secret)
#        COGNEE_API_KEY      (secret)
#        ALLOWED_CHAT_IDS    (variable, comma-separated numeric IDs)
#   4. The Space rebuilds and starts the bot automatically.

FROM python:3.11-slim

# HF Spaces runs containers as user "user" (uid 1000) and expects the app
# to listen on port 7860.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RUN_KEEP_ALIVE=1 \
    KEEP_ALIVE_PORT=7860 \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Install deps as user to avoid permission issues with HF Spaces.
COPY --chown=user:user requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user:user bot.py keep_alive.py ./
# scripts/ is included so you can run the standalone test on the Space if needed.
COPY --chown=user:user scripts ./scripts

USER user
EXPOSE 7860

# HF Spaces runs this; the bot's long-polling starts in parallel with the
# keep-alive HTTP server (RUN_KEEP_ALIVE=1 in bot.py).
CMD ["python", "bot.py"]
