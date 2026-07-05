"""
Quick sanity test for Cognee API calls.
Run this before the bot to make sure your API key works.

Usage: python scripts/test_cognee.py
"""

from __future__ import annotations

import os
import sys
import time

# Allow `from bot import ...` when running from project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from bot import (
    ask_tracker,
    dataset_name_for,
    generate_quiz,
    remember_session,
    reset_memory,
    submit_quiz_feedback,
)

TEST_CHAT_ID = 999_999_999  # isolated dataset just for this test
TEST_TOPIC = "TestTopic"


def banner(msg: str) -> None:
    print("\n" + "=" * 60)
    print(msg)
    print("=" * 60)


def main() -> None:
    load_dotenv()
    if not os.environ.get("COGNEE_API_KEY"):
        print("ERROR: COGNEE_API_KEY is not set. Put it in .env first.")
        sys.exit(1)

    print(f"Using dataset: {dataset_name_for(TEST_CHAT_ID)}")
    print(f"Using base URL: {os.environ.get('COGNEE_API_BASE_URL', 'https://api.cognee.ai')}")

    # 1) remember()
    banner("STEP 1: remember()")
    notes = (
        "Photosynthesis is the process by which green plants use sunlight to "
        "synthesize foods with carbon dioxide and water. The reaction occurs "
        "in the chloroplasts and produces glucose and oxygen as byproducts."
    )
    try:
        result = remember_session(TEST_CHAT_ID, TEST_TOPIC, notes)
        print("OK:", result)
    except Exception as e:
        print("FAILED:", e)
        sys.exit(1)

    # Give Cognee a moment to ingest the memory before we query it.
    print("\nWaiting 10s for Cognee to process the memory…")
    time.sleep(10)

    # 2) recall()
    banner("STEP 2: recall() / ask_tracker()")
    try:
        answer = ask_tracker(TEST_CHAT_ID, "What does photosynthesis produce?")
        print("ANSWER:", answer)
    except Exception as e:
        print("FAILED:", e)

    # 3) generate_quiz()
    banner("STEP 3: generate_quiz()")
    try:
        quiz = generate_quiz(TEST_CHAT_ID, TEST_TOPIC)
        if quiz is None:
            print("Quiz generation returned None (parsing failed or no data).")
        else:
            import json
            print(json.dumps(quiz, indent=2, ensure_ascii=False))
    except Exception as e:
        print("FAILED:", e)

    # 4) submit_quiz_feedback()
    banner("STEP 4: submit_quiz_feedback()")
    try:
        submit_quiz_feedback(TEST_CHAT_ID, TEST_TOPIC, score=2, total=3, wrong=["Q3"])
        print("OK (no exception).")
    except Exception as e:
        print("FAILED:", e)

    # 5) forget() — clean up the test dataset
    banner("STEP 5: forget() / reset_memory()")
    try:
        reset_memory(TEST_CHAT_ID)
        print("OK — test dataset wiped.")
    except Exception as e:
        print("FAILED:", e)

    print("\nDone. If steps 1-3 worked, the bot is good to go.")


if __name__ == "__main__":
    main()
