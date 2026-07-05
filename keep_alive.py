"""
Tiny HTTP keep-alive server for HuggingFace Spaces (free CPU tier).

HF Spaces will put a Docker container to sleep after ~48h of inactivity.
Running this small HTTP server on the port HF expects (7860) AND pinging
it with an external cron (or just letting the bot's long-polling traffic
touch the container) keeps the Space awake.

Run it in a background thread from bot.py when the env var
`RUN_KEEP_ALIVE=1` is set (set by the Dockerfile on HF Spaces).
"""

from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger("keep_alive")

PORT = int(os.environ.get("KEEP_ALIVE_PORT", "7860"))


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"learning-tracker-bot: alive\n")

    def log_message(self, *args: object) -> None:
        # silence default request logging
        pass


def start_in_background() -> None:
    server = HTTPServer(("0.0.0.0", PORT), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="keep_alive")
    thread.start()
    log.info("Keep-alive HTTP server listening on 0.0.0.0:%s", PORT)
