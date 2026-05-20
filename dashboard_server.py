"""
Prefab Dashboard Server
Serves the web.x64 Prefab module asset and exposes REST endpoints
for the agent to receive queries and push live status updates.
"""

import os
import json
import threading
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR  = os.path.join(BASE_DIR, "prefab-dashboard-ui", "modules", "dashboard", "assets", "web.x64")
DATA_DIR   = os.path.join(BASE_DIR, "data")

flask_app = Flask(__name__)


@flask_app.route("/")
def serve_dashboard():
    return send_from_directory(ASSET_DIR, "index.html")


@flask_app.route("/api/query", methods=["POST"])
def receive_query():
    body  = request.get_json(silent=True) or {}
    query = body.get("query", "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    with open(os.path.join(DATA_DIR, "query.json"), "w", encoding="utf-8") as fh:
        json.dump({"query": query}, fh)
    return jsonify({"ok": True})


@flask_app.route("/api/status")
def get_research_status():
    status_file = os.path.join(DATA_DIR, "status.json")
    if os.path.exists(status_file):
        with open(status_file, encoding="utf-8") as fh:
            return jsonify(json.load(fh))
    return jsonify({
        "title":        "Waiting for agent…",
        "steps":        [],
        "company_data": None,
        "completed":    False,
    })


def start_server(port: int = 5000) -> threading.Thread:
    """Start the Flask server in a background daemon thread."""
    server_thread = threading.Thread(
        target=lambda: flask_app.run(port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    return server_thread
