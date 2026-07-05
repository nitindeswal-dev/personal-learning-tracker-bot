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

**The Vision:** For this hackathon, we didn't want to build a complex, heavy web application that users open once and forget. We focused on extreme usability. We wanted to build something you can use **right now**, without downloading new apps or visiting websites that cause friction. 

**The Solution:** An AI brain that lives directly inside your Telegram app, mixing seamlessly into your day-to-day routine. You text it your study notes, voice memos, or lecture PDFs like you're texting a friend. It remembers them forever using [Cognee's](https://cognee.ai) AI Graph Memory. Later, it proactively reminds you to study, answers your questions, and quizzes you strictly on your own material.

Built for the [WeMakeDevs × Cognee Hackathon](https://www.wemakedevs.org/hackathons/cognee) — **Best Use of Cognee Cloud** track.

> ✅ **AI Disclosure:** This project was built with help from AI coding tools. I wrote the spec, designed the architecture, tested everything against real Cognee Cloud, and recorded the demo. The AI helped with boilerplate code and wiring things together.

---

## Try it

👉 [**Open in Telegram**](https://t.me/YOUR_BOT_USERNAME)

1. Tap **Start**
2. `/newtopic React Hooks`
3. `/log React Hooks` → send a text message, attach a PDF, or send a Voice Note!
4. `/ask What is useEffect?` → get an answer grounded in YOUR notes
5. `/quiz React Hooks` → 3 multiple-choice questions from your notes
6. `/remind React Hooks 20:00` → Sets a daily spaced-repetition reminder for 8 PM
7. `/reset` → wipe your Cognee memory

Every user gets their own Cognee dataset (keyed to their Telegram `chat_id`), so your notes are private to you.

---

## Demo

[Demo video placeholder — replace with YouTube/Loom link]

---

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
| `/remind <topic> <HH:MM>` | Sets a daily spaced-repetition reminder | — |
| *(after quiz)* | Feeds score back into Cognee | `remember()` |
| `/reset` | Wipes your Cognee memory | `forget()` |

All Cognee lifecycle operations are seamlessly integrated.

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

## Deploy (HuggingFace Spaces, free)

1. Create a Space at [huggingface.co/new-space](https://huggingface.co/new-space) — SDK: **Docker**, template: **Blank**
2. Push this repo to the Space's git remote
3. Add `TELEGRAM_BOT_TOKEN`, `COGNEE_API_KEY`, and `COGNEE_BASE_URL` as **Secrets** in Space Settings
4. It builds and starts automatically — check the Logs tab

**Keeping it awake 24/7 (Advanced HF Tip):**
HuggingFace Spaces eventually sleep due to inactivity. We engineered a way around this for 100% free hosting:
1. The `Dockerfile` runs our custom `keep_alive.py` HTTP server on port 7860 in the background.
2. You simply set up a free [Cloudflare Worker](https://workers.cloudflare.com/) with a Cron Trigger (e.g. `0 */5 * * *`) that pings your Space URL (`https://your-username-spacename.hf.space`).
3. The Space never sleeps, and your Telegram bot stays online forever. If HF encounters TLS blocking with Telegram API, you can also inject a `TELEGRAM_PROXY_URL` in your HF secrets to instantly route around it!

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
