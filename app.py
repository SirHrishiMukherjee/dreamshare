# DreamShare — standalone Flask app
# ------------------------------------------------------------
# Project layout:
#   dreamshare/
#     app.py
#     requirements.txt
#     templates/
#       base.html
#       index.html
#       compose.html
#       viewer.html
#     static/
#       style.css
#       app.js
#
# Quick start:
#   python -m venv .venv
#   .venv\Scripts\activate        # Windows
#   # source .venv/bin/activate     # macOS/Linux
#   pip install -r requirements.txt
#   set FLASK_APP=app.py            # Windows PowerShell: $env:FLASK_APP="app.py"
#   python app.py
#
# Environment variables:
#   META_AI_API_KEY=your_key_here
#   META_AI_API_URL=https://your-meta-ai-media-endpoint.example/generate
#
# NOTE: Meta AI API details vary by product/access path. This app keeps
# media generation behind generate_media_for_dream(), so you only need to
# replace that function with the exact Meta endpoint payload you receive.

# =========================
# requirements.txt
# =========================
"""
Flask==3.0.3
requests==2.32.3
python-dotenv==1.0.1
"""

# =========================
# app.py
# =========================
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, g, redirect, render_template, request, url_for

import xai_sdk

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "dreamshare.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dreamshare-dev-key")


# ---------- Database ----------
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_: Exception | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS dreams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            dream_text TEXT NOT NULL,
            pov TEXT NOT NULL DEFAULT 'first',
            media_url TEXT,
            media_type TEXT DEFAULT 'video',
            media_status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)
    
    # Safely add media_status column if it doesn't exist (for existing databases)
    try:
        db.execute("ALTER TABLE dreams ADD COLUMN media_status TEXT DEFAULT 'pending'")
        print("✅ media_status column added")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    db.commit()


@app.before_request
def ensure_db() -> None:
    init_db()


# ---------- POV transformation ----------
def convert_first_to_third(text: str) -> str:
    """Simple, readable transformation. For production, use an LLM rewrite endpoint."""
    replacements = [
        (" I ", " the dreamer "),
        (" I'm ", " the dreamer is "),
        (" I’m ", " the dreamer is "),
        (" me ", " the dreamer "),
        (" my ", " the dreamer's "),
        (" mine ", " the dreamer's "),
        (" myself ", " the dreamer "),
    ]
    padded = f" {text} "
    for old, new in replacements:
        padded = padded.replace(old, new)
    padded = padded.strip()
    if padded.startswith("I "):
        padded = "The dreamer " + padded[2:]
    return padded


def display_text(row: sqlite3.Row) -> str:
    text = row["dream_text"]
    if row["pov"] == "third":
        return convert_first_to_third(text)
    return text


# ---------- X AI media generation hook ----------
import threading
import time

def generate_media_in_background(dream_id: int, title: str, dream_text: str):
    """Generate video asynchronously in a background thread."""
    try:
        print(f"[BG] Starting video generation for dream {dream_id}")

        # === X.AI Video Generation ===
        response = requests.post(
            "https://api.x.ai/v1/videos/generations",
            headers={
                "Authorization": f"Bearer {os.environ['XAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-imagine-video",
                "prompt": f"Create dreamlike cinematic media for a dream viewer. Title: {title}. Dream: {dream_text}",
                "duration": 15,
                "aspect_ratio": "16:9",
                "resolution": "720p"
            },
        )
        response.raise_for_status()
        request_id = response.json()["request_id"]

        print(f"[BG] Request ID: {request_id} for dream {dream_id}")

        max_attempts = 80
        for attempt in range(max_attempts):
            response = requests.get(
                f"https://api.x.ai/v1/videos/{request_id}",
                headers={"Authorization": f"Bearer {os.environ['XAI_API_KEY']}"},
            )
            response.raise_for_status()
            data = response.json()
            status = data.get("status")

            if status == "done":
                video_url = data.get("video", {}).get("url")
                if video_url:
                    _save_media_success(dream_id, video_url)
                    print(f"[BG] ✅ Video ready for dream {dream_id}")
                    return
            elif status in ["failed", "expired"]:
                print(f"[BG] ❌ Generation failed for dream {dream_id}")
                break

            time.sleep(3)

        # Failed or timeout
        _save_media_failed(dream_id)

    except Exception as e:
        print(f"[BG] Error for dream {dream_id}: {e}")
        _save_media_failed(dream_id)


# Helper functions to avoid context issues
def _save_media_success(dream_id: int, video_url: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE dreams SET media_url = ?, media_type = ?, media_status = ? WHERE id = ?",
        (video_url, "video", "done", dream_id)
    )
    conn.commit()
    conn.close()


def _save_media_failed(dream_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE dreams SET media_status = 'failed' WHERE id = ?",
        (dream_id,)
    )
    conn.commit()
    conn.close()


# ---------- Routes ----------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    db = get_db()
    if q:
        rows = db.execute(
            """
            SELECT * FROM dreams
            WHERE title LIKE ? OR dream_text LIKE ?
            ORDER BY created_at DESC
            """,
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM dreams ORDER BY created_at DESC").fetchall()
    return render_template("index.html", dreams=rows, q=q)


@app.route("/compose", methods=["GET", "POST"])
def compose():
    if request.method == "POST":
        title = request.form.get("title", "Untitled Dream").strip() or "Untitled Dream"
        dream_text = request.form.get("dream_text", "").strip()
        pov = request.form.get("pov", "first")
        generate = request.form.get("generate_media") == "on"

        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO dreams (title, dream_text, pov, media_url, media_type, media_status, created_at)
            VALUES (?, ?, ?, NULL, 'video', ?, ?)
            """,
            (title, dream_text, pov, 'pending' if generate else 'done', datetime.utcnow().isoformat())
        )
        dream_id = cursor.lastrowid
        db.commit()

        if generate and dream_text:
            # Start background generation
            thread = threading.Thread(
                target=generate_media_in_background,
                args=(dream_id, title, dream_text),
                daemon=True
            )
            thread.start()

        return redirect(url_for("viewer", dream_id=dream_id))

    return render_template("compose.html")


@app.route("/dream/<int:dream_id>")
def viewer(dream_id: int):
    db = get_db()
    dream = db.execute("SELECT * FROM dreams WHERE id = ?", (dream_id,)).fetchone()
    if dream is None:
        return redirect(url_for("index"))

    prev_dream = db.execute(
        "SELECT id FROM dreams WHERE id < ? ORDER BY id DESC LIMIT 1", (dream_id,)
    ).fetchone()
    next_dream = db.execute(
        "SELECT id FROM dreams WHERE id > ? ORDER BY id ASC LIMIT 1", (dream_id,)
    ).fetchone()

    return render_template(
        "viewer.html",
        dream=dream,
        display_text=display_text(dream),
        prev_id=prev_dream["id"] if prev_dream else None,
        next_id=next_dream["id"] if next_dream else None,
    )


@app.route("/regenerate/<int:dream_id>", methods=["POST"])
def regenerate(dream_id: int):
    db = get_db()  # This is fine, it's in request context
    dream = db.execute("SELECT title, dream_text FROM dreams WHERE id = ?", (dream_id,)).fetchone()
    if dream:
        # Reset status
        db.execute(
            "UPDATE dreams SET media_url = NULL, media_status = 'pending' WHERE id = ?",
            (dream_id,)
        )
        db.commit()

        thread = threading.Thread(
            target=generate_media_in_background,
            args=(dream_id, dream["title"], dream["dream_text"]),
            daemon=True
        )
        thread.start()

    return redirect(url_for("viewer", dream_id=dream_id))


@app.route("/api/dream/<int:dream_id>/status")
def dream_status(dream_id: int):
    db = get_db()
    dream = db.execute("SELECT media_status, media_url FROM dreams WHERE id = ?", (dream_id,)).fetchone()
    if dream:
        return {
            "media_status": dream["media_status"],
            "media_url": dream["media_url"]
        }
    return {"media_status": "not_found"}, 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
