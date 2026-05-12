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
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS dreams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            dream_text TEXT NOT NULL,
            pov TEXT NOT NULL DEFAULT 'first',
            media_url TEXT,
            media_type TEXT DEFAULT 'image',
            created_at TEXT NOT NULL
        )
        """
    )
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


# ---------- Meta AI media generation hook ----------
def generate_media_for_dream(title: str, dream_text: str) -> dict[str, Any]:
    """
    Replace this with your Meta AI API call.

    Expected return:
      {"media_url": "...", "media_type": "image" or "video"}

    Current fallback returns a generated SVG data URL, so the app works instantly.
    """
    api_key = os.environ.get("META_AI_API_KEY")
    api_url = os.environ.get("META_AI_API_URL")

    prompt = (
        "Create dreamlike cinematic media for a music-video style dream viewer. "
        f"Title: {title}. Dream: {dream_text}"
    )

    if api_key and api_url:
        try:
            response = requests.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"prompt": prompt, "type": "image"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return {
                "media_url": data.get("media_url") or data.get("url"),
                "media_type": data.get("media_type", "image"),
            }
        except Exception as exc:
            print(f"[DreamShare] Meta AI media generation failed: {exc}")

    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = f"""
    <svg xmlns='http://www.w3.org/2000/svg' width='1280' height='720'>
      <defs>
        <linearGradient id='g' x1='0' x2='1' y1='0' y2='1'>
          <stop stop-color='#151531' offset='0'/>
          <stop stop-color='#41246d' offset='0.45'/>
          <stop stop-color='#111827' offset='1'/>
        </linearGradient>
        <filter id='glow'><feGaussianBlur stdDeviation='8' result='b'/><feMerge><feMergeNode in='b'/><feMergeNode in='SourceGraphic'/></feMerge></filter>
      </defs>
      <rect width='100%' height='100%' fill='url(#g)'/>
      <circle cx='210' cy='160' r='72' fill='#f5d0fe' opacity='0.25' filter='url(#glow)'/>
      <circle cx='980' cy='260' r='115' fill='#93c5fd' opacity='0.16' filter='url(#glow)'/>
      <path d='M0 610 C 260 500, 360 700, 620 570 S 980 480, 1280 620' fill='none' stroke='#e9d5ff' stroke-width='5' opacity='0.45'/>
      <text x='70' y='610' fill='#faf5ff' font-size='52' font-family='Georgia, serif' font-style='italic'>{safe_title}</text>
      <text x='75' y='665' fill='#ddd6fe' font-size='24' font-family='Arial'>DreamShare generated placeholder</text>
    </svg>
    """.strip()
    import base64

    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {"media_url": f"data:image/svg+xml;base64,{encoded}", "media_type": "image"}


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

        media_url = None
        media_type = "image"
        if generate and dream_text:
            media = generate_media_for_dream(title, dream_text)
            media_url = media.get("media_url")
            media_type = media.get("media_type", "image")

        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO dreams (title, dream_text, pov, media_url, media_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, dream_text, pov, media_url, media_type, datetime.utcnow().isoformat()),
        )
        db.commit()
        return redirect(url_for("viewer", dream_id=cursor.lastrowid))

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
    db = get_db()
    dream = db.execute("SELECT * FROM dreams WHERE id = ?", (dream_id,)).fetchone()
    if dream:
        media = generate_media_for_dream(dream["title"], dream["dream_text"])
        db.execute(
            "UPDATE dreams SET media_url = ?, media_type = ? WHERE id = ?",
            (media.get("media_url"), media.get("media_type", "image"), dream_id),
        )
        db.commit()
    return redirect(url_for("viewer", dream_id=dream_id))


if __name__ == "__main__":
    app.run(debug=True)
