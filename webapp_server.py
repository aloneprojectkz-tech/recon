"""
Flask web server for Blackbird OSINT webapp.
Serves the frontend and provides async search API endpoints.
"""

import os
import sys
import uuid
import asyncio
import threading
import logging
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from blackbird_runner import search_username, search_email, search_email_full, search_phone

logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="webapp")

# In-memory task store  {task_id: {status, progress, result, message}}
tasks = {}
tasks_lock = threading.Lock()


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("webapp", "index.html")


@app.route("/webapp/<path:filename>")
def static_files(filename):
    return send_from_directory("webapp", filename)


# ── Search API ────────────────────────────────────────────────────────────────

@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    search_type = data.get("type", "username").lower()

    if not query:
        return jsonify({"error": "Query is required"}), 400
    if search_type not in ("username", "email", "phone"):
        return jsonify({"error": "Type must be username, email or phone"}), 400

    task_id = str(uuid.uuid4())

    with tasks_lock:
        tasks[task_id] = {"status": "running", "progress": 0, "result": None, "message": ""}

    # Run search in a background thread with its own event loop
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def progress_cb(done, total):
            pct = int(done / total * 100) if total else 0
            with tasks_lock:
                if task_id in tasks:
                    tasks[task_id]["progress"] = pct

        try:
            if search_type == "username":
                result = loop.run_until_complete(search_username(query, progress_cb))
            elif search_type == "email":
                result = loop.run_until_complete(search_email_full(query, progress_cb))
            else:
                result = loop.run_until_complete(search_phone(query))

            with tasks_lock:
                tasks[task_id]["status"] = "done"
                tasks[task_id]["progress"] = 100
                tasks[task_id]["result"] = result
        except Exception as e:
            logger.error(f"Search error: {e}", exc_info=True)
            with tasks_lock:
                tasks[task_id]["status"] = "error"
                tasks[task_id]["message"] = str(e)
        finally:
            loop.close()

        # Clean up old tasks (keep only last 100)
        with tasks_lock:
            if len(tasks) > 100:
                old_keys = list(tasks.keys())[:-100]
                for k in old_keys:
                    del tasks[k]

    t = threading.Thread(target=run, daemon=True)
    t.start()

    return jsonify({"task_id": task_id})


@app.route("/api/status/<task_id>")
def api_status(task_id):
    with tasks_lock:
        task = tasks.get(task_id)

    if not task:
        return jsonify({"error": "Task not found"}), 404

    return jsonify({
        "status":   task["status"],
        "progress": task["progress"],
        "result":   task["result"],
        "message":  task["message"],
    })


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info(f"Starting Blackbird webapp on port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
