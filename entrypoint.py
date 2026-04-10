#!/usr/bin/env python3
"""
Entrypoint: запускает Telegram-бота и веб-сервер одновременно.
"""

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("entrypoint")


def run_webserver():
    """Run Flask webapp in a subprocess."""
    port = os.getenv("WEB_PORT", "5000")
    logger.info(f"Starting webapp on port {port}...")
    while True:
        try:
            proc = subprocess.Popen(
                [sys.executable, "webapp_server.py"],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            proc.wait()
            logger.warning("Webapp process exited, restarting in 3s...")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Webapp error: {e}")
            time.sleep(5)


def run_bot():
    """Run aiogram bot."""
    logger.info("Starting Telegram bot...")
    while True:
        try:
            proc = subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            proc.wait()
            logger.warning("Bot process exited, restarting in 3s...")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Bot error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    mode = os.getenv("RUN_MODE", "both")  # both | bot | web

    if mode == "web":
        run_webserver()
    elif mode == "bot":
        run_bot()
    else:
        # Run both
        web_thread = threading.Thread(target=run_webserver, daemon=True)
        web_thread.start()

        # Small delay so web starts first
        time.sleep(1)

        # Bot runs in main thread
        run_bot()
