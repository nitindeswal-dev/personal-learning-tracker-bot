---
title: Personal Learning Tracker Bot
emoji: 📚
colorFrom: indigo
colorTo: blue
sdk: docker
app_file: Dockerfile
pinned: false
---

# 📚 Personal Learning Tracker — Telegram Bot

**The Vision:** To build a learning tool with zero friction. Instead of a complex web app, this project provides an AI assistant that lives directly inside Telegram.

**The Solution:** You message the bot your study notes, lecture PDFs, or Voice Notes. It processes the information and remembers it permanently using [Cognee's](https://cognee.ai) AI Graph Memory. Later, you can ask it questions or generate personalized quizzes based strictly on your own material.

Built for the [WeMakeDevs × Cognee Hackathon](https://www.wemakedevs.org/hackathons/cognee) — **Best Use of Cognee Cloud** track.

> ✅ **AI Disclosure:** This project was built with help from AI coding tools. I wrote the spec, designed the architecture, tested everything against real Cognee Cloud, and recorded the demo. The AI helped with boilerplate code and wiring things together.

---

## Try it

👉 [**Open in Telegram**](https://t.me/learning_tracker_ai_bot)

1. Tap **Start**
2. `/newtopic React Hooks`
3. `/log React Hooks` → send a text message, attach a PDF, or send a Voice Note!
4. `/ask What is useEffect?` → get an answer grounded in YOUR notes
5. `/quiz React Hooks` → 3 multiple-choice questions from your notes
6. `/reset` → wipe your Cognee memory

Every user gets their own Cognee dataset (keyed to their Telegram `chat_id`), so your notes are private to you.



## How it works

```
Telegram user  →  Telegram servers  →  bot.py (long-polling)
                                            │              │
                                            ▼              ▼
                                       SQLite file    Cognee Cloud API
                                    (topics, sessions)  (per-user dataset)
```

| Command | What happens | Cognee call |
|---|---|---|
| `/newtopic <name>` | Creates a topic locally | — |
| `/topics` | Lists your topics + stats | — |
| `/log <topic>` → send text/pdf/voice | Streams Text, Documents, or AssemblyAI transcribed Voice to Cognee | `remember()` |
| `/ask <question>` | Answers from your notes | `recall()` |
| `/quiz <topic>` | 3 MCQs from your material | `recall()` |
| *(after quiz)* | Feeds score back into Cognee | `remember()` |
| `/reset` | Wipes your Cognee memory | `forget()` |


**Why a Telegram bot?** Free UI, free per-user identity via `chat_id` (no auth code needed), and zero deploy risk — long-polling just works, no public URL required.

---

## Run it yourself

**1. Get tokens (free)**

- `TELEGRAM_BOT_TOKEN` — message [@BotFather](https://t.me/BotFather) → `/newbot`
- `COGNEE_API_KEY` — sign up at [cognee.ai](https://cognee.ai), use code `COGNEE-35` for free Developer plan
- `ASSEMBLYAI_API_KEY` (Optional) — sign up at [assemblyai.com](https://www.assemblyai.com/) for Voice Note support

**2. Setup**

```bash
git clone https://github.com/YOUR_USERNAME/learning-tracker-bot.git
cd learning-tracker-bot
cp .env.example .env   # fill in your tokens
pip install -r requirements.txt
```

**3. Run**

```bash
python scripts/test_cognee.py   # optional: verify your API key works
python bot.py                   # starts the bot
```

---

## Deploy (Highly-Available, Zero-Cost Architecture)

This bot is designed to be deployed for **$0/month** using an advanced edge-routing architecture. While standard bot deployments on platforms like Render or Heroku are simpler, we opted for **HuggingFace Spaces (Docker)** paired with a **Cloudflare Worker Edge Proxy** to demonstrate robust network engineering and bypass strict outbound firewall limitations.

**Deployment Steps:**
1. Create a Space at [huggingface.co/new-space](https://huggingface.co/new-space) (SDK: **Docker**, Template: **Blank**).
2. Push this repo to the Space's git remote.
3. Add `TELEGRAM_BOT_TOKEN`, `COGNEE_API_KEY`, `ASSEMBLYAI_API_KEY`, and `COGNEE_BASE_URL` as **Secrets**.
4. **The Edge Proxy:** Because HuggingFace firewalls outbound calls to Telegram, you must configure a lightweight Cloudflare Worker to act as a reverse proxy. Add your worker URL as `TELEGRAM_PROXY_URL` in Secrets. The `bot.py` uses `python-telegram-bot`'s `base_file_url` to elegantly route all API polling *and* binary file downloads (Voice/PDF) through this proxy with custom timeouts.

**Keeping it awake 24/7:**
HuggingFace Spaces sleep after 48 hours of inactivity. To ensure 100% uptime:
1. The `Dockerfile` natively spins up a custom `keep_alive.py` ASGI server on port 7860.
2. A cron-triggered Cloudflare Worker periodically pings this port, ensuring the underlying container is never suspended and your Cognee assistant is always ready.

By relying on `/tmp/` file handling and stateless edge-proxying, this bot achieves enterprise-grade resilience on entirely free tiers.

---

## Project structure

```
bot.py              — the whole bot (single file)
keep_alive.py       — HTTP server for HF Spaces health checks
scripts/test_cognee.py — standalone Cognee API test
Dockerfile          — HF Spaces deployment
.env.example        — template for secrets
```

---

## Troubleshooting

- **Bot doesn't reply** → check console for errors; make sure `ALLOWED_CHAT_IDS` is empty (open access)
- **Cognee calls fail** → verify your API key with `python scripts/test_cognee.py`
- **Quiz says "couldn't generate"** → log more notes first, Cognee needs material to work with
- **Two instances fighting** → only run one instance per bot token (stop local before deploying)

---

## License

MIT — see [LICENSE](./LICENSE).
