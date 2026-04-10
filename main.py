#!/usr/bin/env python3
"""
main.py — запускает веб-сервер и Telegram-бота одновременно.
Использование: python main.py
"""

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
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


def run_webserver():
    port = os.getenv("WEB_PORT", "5000")
    logger.info(f"Web server starting on http://0.0.0.0:{port}")
    while True:
        try:
            proc = subprocess.Popen([sys.executable, "webapp_server.py"],
                                    stdout=sys.stdout, stderr=sys.stderr)
            proc.wait()
            logger.warning("Web server stopped, restarting in 3s...")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Web server error: {e}")
            time.sleep(5)


def run_bot():
    logger.info("Telegram bot starting...")
    while True:
        try:
            proc = subprocess.Popen([sys.executable, "bot.py"],
                                    stdout=sys.stdout, stderr=sys.stderr)
            proc.wait()
            logger.warning("Bot stopped, restarting in 3s...")
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
        web_thread = threading.Thread(target=run_webserver, daemon=True)
        web_thread.start()
        time.sleep(1)
        run_bot()
