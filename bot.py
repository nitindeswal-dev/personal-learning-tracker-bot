"""
Personal Learning Tracker — Telegram Bot

Run: cp .env.example .env && fill in tokens, pip install -r requirements.txt, python bot.py
Deploy: HuggingFace Spaces (Docker SDK). See README.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import closing
from typing import Any

import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)
from telegram.helpers import escape_markdown

load_dotenv()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
COGNEE_API_KEY = os.environ.get("COGNEE_API_KEY", "")
COGNEE_BASE_URL = os.environ.get("COGNEE_BASE_URL", "").rstrip("/")
DB_PATH = os.environ.get("DB_PATH", "tracker.db")

# Optional allowlist — empty = open access (anyone can use)
_allowed_raw = os.environ.get("ALLOWED_CHAT_IDS", "")
ALLOWED_CHAT_IDS: set[int] = {
    int(x.strip()) for x in _allowed_raw.split(",") if x.strip().isdigit()
}
OPEN_MODE = not ALLOWED_CHAT_IDS

# Reverse proxy for Telegram API (needed on HF Spaces which blocks api.telegram.org)
TELEGRAM_PROXY_URL = os.environ.get("TELEGRAM_PROXY_URL", "").rstrip("/")

RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "20"))
_user_msg_times: dict[int, deque[float]] = defaultdict(deque)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.DEBUG,
)
log = logging.getLogger("learning_tracker")


def dataset_name_for(chat_id: int) -> str:
    return f"learning_tracker_{chat_id}"



def _rate_limited(chat_id: int) -> bool:
    if RATE_LIMIT_PER_MIN <= 0:
        return False
    now = time.time()
    window = _user_msg_times[chat_id]
    while window and now - window[0] > 60.0:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_MIN:
        return True
    window.append(now)
    return False



# --- SQLite ---
SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER REFERENCES topics(id),
    notes TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER REFERENCES topics(id),
    score INTEGER,
    total INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db() -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn



def create_topic(chat_id: int, name: str) -> int:
    with closing(db_conn()) as conn:
        cur = conn.execute(
            "INSERT INTO topics (chat_id, name) VALUES (?, ?)", (chat_id, name)
        )
        conn.commit()
        return cur.lastrowid


def get_topic_by_name(chat_id: int, name: str) -> sqlite3.Row | None:
    # case-insensitive, exact match
    with closing(db_conn()) as conn:
        return conn.execute(
            "SELECT * FROM topics WHERE chat_id = ? AND LOWER(name) = LOWER(?)",
            (chat_id, name),
        ).fetchone()


def get_topic_by_id(topic_id: int) -> sqlite3.Row | None:
    with closing(db_conn()) as conn:
        return conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()


def list_topics_with_stats(chat_id: int) -> list[sqlite3.Row]:
    sql = """
        SELECT t.id, t.name, t.created_at,
               (SELECT COUNT(*) FROM study_sessions s WHERE s.topic_id = t.id) AS session_count,
               (SELECT q.score FROM quiz_attempts q
                  WHERE q.topic_id = t.id ORDER BY q.created_at DESC LIMIT 1) AS last_score,
               (SELECT q.total FROM quiz_attempts q
                  WHERE q.topic_id = t.id ORDER BY q.created_at DESC LIMIT 1) AS last_total
        FROM topics t
        WHERE t.chat_id = ?
        ORDER BY t.created_at DESC
    """
    with closing(db_conn()) as conn:
        return conn.execute(sql, (chat_id,)).fetchall()



def save_session(topic_id: int, notes: str) -> int:
    with closing(db_conn()) as conn:
        cur = conn.execute(
            "INSERT INTO study_sessions (topic_id, notes) VALUES (?, ?)",
            (topic_id, notes),
        )
        conn.commit()
        return cur.lastrowid



def save_quiz_attempt(topic_id: int, score: int, total: int) -> int:
    with closing(db_conn()) as conn:
        cur = conn.execute(
            "INSERT INTO quiz_attempts (topic_id, score, total) VALUES (?, ?, ?)",
            (topic_id, score, total),
        )
        conn.commit()
        return cur.lastrowid



# --- Cognee API calls (sync — wrapped with asyncio.to_thread in handlers) ---


def _check_cognee_env() -> None:
    if not COGNEE_API_KEY:
        raise RuntimeError(
            "COGNEE_API_KEY is not set. Add it to .env (see .env.example)."
        )
    if not COGNEE_BASE_URL:
        raise RuntimeError(
            "COGNEE_BASE_URL is not set. Add your tenant URL to .env."
        )


def remember_session(chat_id: int, topic_name: str, notes: str | bytes, file_name: str = "notes.txt") -> dict[str, Any]:
    _check_cognee_env()
    resp = requests.post(
        f"{COGNEE_BASE_URL}/api/v1/remember",
        headers={"X-Api-Key": COGNEE_API_KEY},
        files={"data": (file_name, notes)},
        data={
            "datasetName": dataset_name_for(chat_id),
            "node_set": topic_name,
            "run_in_background": "false",
        },
        timeout=120,
    )
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


def ask_tracker(chat_id: int, question: str) -> str:
    _check_cognee_env()
    resp = requests.post(
        f"{COGNEE_BASE_URL}/api/v1/recall",
        headers={"X-Api-Key": COGNEE_API_KEY, "Content-Type": "application/json"},
        json={
            "query": question,
            "datasets": [dataset_name_for(chat_id)],
            "search_type": "GRAPH_COMPLETION",
            "top_k": 10,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return _extract_answer_text(resp.json())


def _extract_answer_text(payload: Any) -> str:
    """Cognee responses come in various shapes — normalize to a plain string."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, list):

        parts = []
        for item in payload:
            if isinstance(item, dict):
                parts.append(item.get("content") or item.get("text") or item.get("answer") or json.dumps(item))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p).strip()
    if isinstance(payload, dict):

        for key in ("content", "text", "answer", "data", "response", "result", "message"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, list) and v:
                return _extract_answer_text(v)

        return json.dumps(payload, ensure_ascii=False)[:2000]
    return str(payload).strip()


def generate_quiz(chat_id: int, topic_name: str) -> list[dict] | None:
    _check_cognee_env()
    prompt = (
        f"Based only on what I have studied about '{topic_name}', generate exactly 3 "
        f"multiple-choice quiz questions to test my understanding. Return ONLY valid JSON, "
        f"no markdown, no explanation, in this exact shape: "
        f'[{{"question":"...","options":["A","B","C","D"],"correctIndex":0}}]'
    )
    resp = requests.post(
        f"{COGNEE_BASE_URL}/api/v1/recall",
        headers={"X-Api-Key": COGNEE_API_KEY, "Content-Type": "application/json"},
        json={
            "query": prompt,
            "datasets": [dataset_name_for(chat_id)],
            "node_name": [topic_name],
            "search_type": "GRAPH_COMPLETION",
            "top_k": 10,
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json()
    text = _extract_answer_text(raw)


    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        log.warning("generate_quiz: no JSON array found in response: %s", text[:300])
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        log.warning("generate_quiz: JSON decode failed: %s | text: %s", e, text[:300])
        return None

    if not isinstance(parsed, list) or not parsed:
        return None


    cleaned: list[dict] = []
    for q in parsed:
        if (
            isinstance(q, dict)
            and isinstance(q.get("question"), str)
            and isinstance(q.get("options"), list)
            and len(q["options"]) >= 2
            and isinstance(q.get("correctIndex"), int)
            and 0 <= q["correctIndex"] < len(q["options"])
        ):
            cleaned.append(q)
    return cleaned or None


def submit_quiz_feedback(
    chat_id: int, topic_name: str, score: int, total: int, wrong: list[str]
) -> None:

    _check_cognee_env()
    summary = (
        f"Quiz result for topic '{topic_name}': scored {score}/{total}. "
        f"Questions the user got wrong: {'; '.join(wrong) or 'none'}."
    )
    try:
        requests.post(
            f"{COGNEE_BASE_URL}/api/v1/remember",
            headers={"X-Api-Key": COGNEE_API_KEY},
            files={"data": ("quiz_feedback.txt", summary)},
            data={
                "datasetName": dataset_name_for(chat_id),
                "node_set": topic_name,
                "run_in_background": "false",
            },
            timeout=120,
        ).raise_for_status()
    except requests.RequestException as e:
        log.warning("submit_quiz_feedback: remember() failed: %s", e)


def reset_memory(chat_id: int) -> None:
    _check_cognee_env()
    requests.post(
        f"{COGNEE_BASE_URL}/api/v1/forget",
        headers={"X-Api-Key": COGNEE_API_KEY, "Content-Type": "application/json"},
        json={"dataset": dataset_name_for(chat_id), "memory_only": False},
        timeout=120,
    ).raise_for_status()



def _esc(text: str) -> str:
    return escape_markdown(text, version=1)


async def _reply_or_send(update: Update, text: str) -> None:
    target = update.message or (update.callback_query and update.callback_query.message)
    if target:
        await target.reply_text(text)


async def check_allowed(update: Update, *, is_callback: bool = False) -> bool:
    chat = update.effective_chat
    if chat is None:
        return False
    if ALLOWED_CHAT_IDS and chat.id not in ALLOWED_CHAT_IDS:
        try:
            await _reply_or_send(
                update, "This bot is private during the hackathon judging period."
            )
        except Exception:
            pass
        return False
    # Skip rate limit for button taps
    if not is_callback and _rate_limited(chat.id):
        try:
            await _reply_or_send(
                update,
                "⏳ Slow down — you're sending messages too fast. Try again in a minute.",
            )
        except Exception:
            pass
        return False
    return True



# --- Command handlers ---
HELP_TEXT = (
    "*Personal Learning Tracker*\n"
    "Message me your study notes — I remember them with Cognee, answer questions "
    "grounded in what you've studied, and quiz you on your own material.\n\n"
    "*Commands*\n"
    "/newtopic `<name>` — create a topic\n"
    "/topics — list your topics + session counts + last quiz score\n"
    "/log `<topic name>` — then send your notes as the next message\n"
    "/ask `<question>` — answer grounded in your notes (Cognee recall)\n"
    "/quiz `<topic name>` — 3 multiple-choice questions on that topic\n"
    "/reset — wipe your Cognee memory (with Yes/No confirm)\n"
    "/cancel — abort an in-progress note entry or quiz\n"
    "/help — show this message\n\n"
    "_Powered by Cognee Cloud — remember, recall, improve, forget._"
)

WELCOME_TEXT = (
    "👋 *Welcome to Personal Learning Tracker!*\n\n"
    "I'm a Telegram bot that remembers what *you* study — powered by "
    "[Cognee's](https://cognee.ai) memory layer.\n\n"
    "*Try me in 30 seconds:*\n"
    "1. `/newtopic React Hooks` — create a topic\n"
    "2. `/log React Hooks` — then send me 2-3 sentences of notes\n"
    "3. `/ask What is useEffect?` — I'll answer from YOUR notes\n"
    "4. `/quiz React Hooks` — 3 multiple-choice questions on what you logged\n\n"
    "*Why this exists:* every LLM call is stateless — it forgets you the moment "
    "the request ends. Cognee fixes that with a `remember → recall → improve → "
    "forget` lifecycle, and this bot shows the whole cycle inside a normal "
    "Telegram chat. No web app, no login.\n\n"
    "Your data is isolated — every Telegram user gets their own Cognee dataset "
    "keyed to their `chat_id`. So your notes are *your* notes.\n\n"
    "Type /help anytime to see all commands. Have fun studying! 📚"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return
    await update.message.reply_text(WELCOME_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_newtopic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /newtopic <topic name>")
        return
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Topic name can't be empty.")
        return

    chat_id = update.effective_chat.id
    existing = get_topic_by_name(chat_id, name)
    if existing:
        await update.message.reply_text(f"Topic '{name}' already exists.")
        return

    topic_id = create_topic(chat_id, name)
    await update.message.reply_text(
        f"Created topic *{_esc(name)}* (id {topic_id}).\nUse /log {_esc(name)} to start adding notes.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return
    chat_id = update.effective_chat.id
    rows = list_topics_with_stats(chat_id)
    if not rows:
        await update.message.reply_text(
            "No topics yet. Create one with /newtopic <name>."
        )
        return

    lines = ["*Your topics*\n"]
    for r in rows:
        last = (
            f"last quiz: {r['last_score']}/{r['last_total']}"
            if r["last_score"] is not None and r["last_total"] is not None
            else "no quizzes yet"
        )
        lines.append(f"• *{_esc(r['name'])}* — {r['session_count']} session(s), {last}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /log <topic name>")
        return
    name = " ".join(context.args).strip()
    chat_id = update.effective_chat.id
    topic = get_topic_by_name(chat_id, name)
    if not topic:
        create_topic(chat_id, name)
        topic = get_topic_by_name(chat_id, name)

    context.user_data["awaiting_notes_for"] = topic["id"]
    context.user_data["awaiting_notes_topic_name"] = topic["name"]
    await update.message.reply_text(
        f"Send me your notes for *{_esc(topic['name'])}* as your next message. "
        f"They'll be saved locally AND sent to Cognee.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return

    if context.user_data.get("quiz"):
        await update.message.reply_text(
            "You have a quiz in progress — tap an answer button, or /cancel to abort."
        )
        return

    topic_id = context.user_data.get("awaiting_notes_for")
    topic_name = context.user_data.get("awaiting_notes_topic_name")
    if not topic_id or not topic_name:
        await update.message.reply_text(
            "I didn't recognize that. Try /log <topic> first."
        )
        return

    doc = update.message.document
    if doc.file_size and doc.file_size > 10 * 1024 * 1024:
        await update.message.reply_text("File is too large! Maximum 10MB supported.")
        return

    await update.message.reply_text(
        f"Downloading {doc.file_name} and sending to Cognee (topic: {_esc(topic_name)})... This may take a minute!",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        
        chat_id = update.effective_chat.id
        await asyncio.to_thread(save_session, topic_id, f"Uploaded document: {doc.file_name}")
        await asyncio.to_thread(
            remember_session, 
            chat_id=chat_id, 
            topic_name=topic_name, 
            notes=bytes(file_bytes), 
            file_name=doc.file_name
        )
        
        del context.user_data["awaiting_notes_for"]
        del context.user_data["awaiting_notes_topic_name"]
        await update.message.reply_text(
            f"Done — Cognee remembered your document for {topic_name}. Try /ask or /quiz {topic_name} now."
        )
    except Exception as e:
        log.exception("handle_document failed")
        await update.message.reply_text(f"Cognee remember() failed for file: {e}")

async def handle_plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return


    if context.user_data.get("quiz"):
        await update.message.reply_text(
            "You have a quiz in progress — tap an answer button, or /cancel to abort."
        )
        return

    topic_id = context.user_data.get("awaiting_notes_for")
    topic_name = context.user_data.get("awaiting_notes_topic_name")
    if not topic_id or not topic_name:
        await update.message.reply_text(
            "I didn't recognize that. Try /help to see what I can do."
        )
        return

    notes = update.message.text or ""
    chat_id = update.effective_chat.id


    context.user_data.pop("awaiting_notes_for", None)
    context.user_data.pop("awaiting_notes_topic_name", None)

    save_session(topic_id, notes)
    safe_name = _esc(topic_name)
    await update.message.reply_text(
        f"Saved locally. Sending to Cognee (topic: *{safe_name}*)…",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        result = await asyncio.to_thread(remember_session, chat_id, topic_name, notes)
        log.info("remember_session ok: %s", str(result)[:200])
        await update.message.reply_text(
            f"Done — Cognee remembers your notes for *{safe_name}*. "
            f"Try /ask or /quiz {safe_name} now.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        log.exception("remember_session failed")
        await update.message.reply_text(
            f"Saved locally, but Cognee remember() failed: {e}\n"
            f"Your notes are still in SQLite; Cognee just didn't get them."
        )


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ask <your question>")
        return
    question = " ".join(context.args).strip()
    chat_id = update.effective_chat.id

    await update.message.reply_text("Asking Cognee (recall)…")
    try:
        answer = await asyncio.to_thread(ask_tracker, chat_id, question)
    except Exception as e:
        log.exception("ask_tracker failed")
        await update.message.reply_text(f"Cognee recall() failed: {e}")
        return

    if not answer:
        await update.message.reply_text(
            "Cognee didn't return an answer. Try logging more notes first (/log <topic>)."
        )
        return


    for i in range(0, len(answer), 4000):
        await update.message.reply_text(answer[i : i + 4000])


async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /quiz <topic name>")
        return
    name = " ".join(context.args).strip()
    chat_id = update.effective_chat.id
    topic = get_topic_by_name(chat_id, name)
    if not topic:
        create_topic(chat_id, name)
        topic = get_topic_by_name(chat_id, name)

    await update.message.reply_text(
        f"Generating 3 quiz questions for *{_esc(topic['name'])}*…",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        questions = await asyncio.to_thread(generate_quiz, chat_id, topic["name"])
    except Exception as e:
        log.exception("generate_quiz failed")
        await update.message.reply_text(f"Cognee quiz generation failed: {e}")
        return

    if not questions:
        await update.message.reply_text(
            "Couldn't generate a quiz for that topic yet. Log more notes first "
            f"with /log {topic['name']}, then try again."
        )
        return


    questions = questions[:3]
    context.user_data["quiz"] = {
        "topic_id": topic["id"],
        "topic_name": topic["name"],
        "questions": questions,
        "current": 0,
        "score": 0,
        "wrong": [],
    }
    await _send_quiz_question(update, context, question_index=0)


async def _send_quiz_question(
    update: Update, context: ContextTypes.DEFAULT_TYPE, question_index: int
) -> None:
    quiz = context.user_data["quiz"]
    q = quiz["questions"][question_index]
    buttons = [
        [InlineKeyboardButton(opt, callback_data=f"quiz_{question_index}_{i}")]
        for i, opt in enumerate(q["options"])
    ]
    header = f"Q{question_index + 1}/{len(quiz['questions'])} — *{_esc(quiz['topic_name'])}*"
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"{header}\n\n{q['question']}",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_quiz_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await check_allowed(update, is_callback=True):
        return
    query = update.callback_query
    await query.answer()

    quiz = context.user_data.get("quiz")
    if not quiz:
        await query.edit_message_text("This quiz is no longer active. Use /quiz <topic>.")
        return

    try:
        _, q_index_str, chosen_str = query.data.split("_")
        q_index = int(q_index_str)
        chosen = int(chosen_str)
    except ValueError:
        await query.edit_message_text("Malformed quiz response. Try /quiz again.")
        return

    if q_index != quiz["current"]:
        return

    q = quiz["questions"][q_index]
    correct_idx = q["correctIndex"]
    is_correct = chosen == correct_idx
    if is_correct:
        quiz["score"] += 1
        verdict = "Correct"
    else:
        correct_letter = chr(ord("A") + correct_idx)
        quiz["wrong"].append(f"{q['question']} (correct: {correct_letter})")
        verdict = f"Wrong — correct answer was {q['options'][correct_idx]}"


    try:
        await query.edit_message_text(
            f"{q['question']}\n\nYour answer: {q['options'][chosen]}\n{verdict}"
        )
    except Exception:

        pass

    next_index = q_index + 1
    if next_index < len(quiz["questions"]):
        quiz["current"] = next_index
        await _send_quiz_question(update, context, next_index)
        return


    score = quiz["score"]
    total = len(quiz["questions"])
    topic_id = quiz["topic_id"]
    topic_name = quiz["topic_name"]
    wrong = quiz["wrong"]

    save_quiz_attempt(topic_id, score, total)


    if score == total:
        emoji_line = "Perfect. Cognee now knows you've mastered this."
    elif score == 0:
        emoji_line = "Tough round — log more notes and try again."
    else:
        emoji_line = "Good effort — see the correct answers above."
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"*Quiz complete: {score}/{total}* on *{topic_name}*.\n"
            f"{emoji_line}\n\n"
            f"Feeding this result back into Cognee (remember + improve)…"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


    try:
        await asyncio.to_thread(
            submit_quiz_feedback, update.effective_chat.id, topic_name, score, total, wrong
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Done — Cognee has logged your quiz result. "
            "Your future /ask answers should reflect what you actually know.",
        )
    except Exception as e:
        log.exception("submit_quiz_feedback failed")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"(Feedback step failed: {e}. Your score is still saved locally.)",
        )

    context.user_data.pop("quiz", None)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return
    keyboard = [
        [
            InlineKeyboardButton("Yes, wipe my memory", callback_data="reset_yes"),
            InlineKeyboardButton("No, cancel", callback_data="reset_no"),
        ]
    ]
    await update.message.reply_text(
        "This will call Cognee forget() on your dataset and erase everything "
        "Cognee knows about your study notes. Local SQLite rows are kept. "
        "Are you sure?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_reset_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await check_allowed(update, is_callback=True):
        return
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "reset_no":
        await query.edit_message_text("Reset cancelled. Nothing was changed.")
        return


    await query.edit_message_text("Calling Cognee forget()…")
    try:
        await asyncio.to_thread(reset_memory, update.effective_chat.id)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Done. Cognee has forgotten everything for your account. "
            "Your local SQLite notes are still on disk if you want them.",
        )
    except Exception as e:
        log.exception("reset_memory failed")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Cognee forget() failed: {e}",
        )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_allowed(update):
        return
    context.user_data.pop("awaiting_notes_for", None)
    context.user_data.pop("awaiting_notes_topic_name", None)
    context.user_data.pop("quiz", None)
    await update.message.reply_text("Cancelled any in-progress flow.")



import socket

# Apply DNS patch for HF Spaces blocking *.workers.dev
_orig_getaddrinfo = socket.getaddrinfo

def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    host_str = host.decode('utf-8') if isinstance(host, bytes) else host
    if host_str and host_str.endswith(".workers.dev"):
        return _orig_getaddrinfo("104.21.72.19", port, family, type, proto, flags)
    return _orig_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = custom_getaddrinfo

def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it to .env (see .env.example)."
        )

    builder = Application.builder().token(BOT_TOKEN)
    if TELEGRAM_PROXY_URL:
        builder = builder.base_url(f"{TELEGRAM_PROXY_URL}/bot")
        log.info("Using Telegram proxy: %s", TELEGRAM_PROXY_URL)
    app = builder.build()

    async def debug_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.info(f"RECEIVED UPDATE ID: {update.update_id}")

    app.add_handler(TypeHandler(Update, debug_update), group=-1)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("newtopic", cmd_newtopic))
    app.add_handler(CommandHandler("topics", cmd_topics))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("quiz", cmd_quiz))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("cancel", cmd_cancel))


    app.add_handler(
        CallbackQueryHandler(handle_quiz_callback, pattern=r"^quiz_\d+_\d+$")
    )
    app.add_handler(
        CallbackQueryHandler(handle_reset_callback, pattern=r"^reset_(yes|no)$")
    )


    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_plain_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    return app


def main() -> None:
    init_db()
    log.info("DB initialized at %s", DB_PATH)
    if OPEN_MODE:
        log.warning(
            "OPEN MODE — anyone who finds the bot can use it. "
            "Per-user rate limit: %s msgs/min. Set ALLOWED_CHAT_IDS to lock down.",
            RATE_LIMIT_PER_MIN or "disabled",
        )
    else:
        log.info("LOCKED MODE — allowed chat IDs: %s", ALLOWED_CHAT_IDS)

    # HF Spaces keep-alive server
    if os.environ.get("RUN_KEEP_ALIVE", "0") == "1":
        try:
            from keep_alive import start_in_background

            start_in_background()
        except Exception as e:
            log.warning("keep_alive failed to start: %s", e)

    app = build_application()
    log.info("Starting long-polling bot. Press Ctrl+C to stop.")
    # Rely on completely default polling settings to avoid any serialization/timeout
    # Run manual polling to bypass the PTB Updater connection logic which is failing
    # with Cloudflare Workers' TLS handshake on HF Spaces.
    async def manual_polling():
        await app.initialize()
        await app.start()
        
        # Register commands with Telegram so they appear in the / menu
        from telegram import BotCommand
        commands = [
            BotCommand("start", "Start the bot and see welcome message"),
            BotCommand("help", "See the list of commands and how to use them"),
            BotCommand("newtopic", "Create a new study topic"),
            BotCommand("topics", "List all your topics"),
            BotCommand("log", "Log notes/information for a topic"),
            BotCommand("ask", "Ask a question about your logged notes"),
            BotCommand("quiz", "Generate a quiz for a topic"),
            BotCommand("reset", "Delete all your data (IRREVERSIBLE)"),
            BotCommand("cancel", "Cancel current action"),
        ]
        await app.bot.set_my_commands(commands)
        
        log.info("Started manual polling loop.")
        offset = 0
        while True:
            try:
                # Use short timeout for Cloudflare Workers
                updates = await app.bot.get_updates(offset=offset, timeout=10)
                for update in updates:
                    await app.process_update(update)
                    offset = update.update_id + 1
            except Exception as e:
                log.error("Manual polling error: %s", e)
                await asyncio.sleep(2)
                
    import asyncio
    asyncio.run(manual_polling())


if __name__ == "__main__":
    main()
