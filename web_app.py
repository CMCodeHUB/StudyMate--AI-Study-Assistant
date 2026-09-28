"""
StudyMate — Web UI backend.

A thin Flask layer over the existing LangGraph agent (agent.py) and task
database (db.py). Importing `agent` builds the vector store, the Gemini LLM,
and the compiled LangGraph graph exactly once at startup — the same objects
the CLI version (`python agent.py`) uses.

Accounts: users sign up / log in with an email and password. Passwords are
stored hashed (never in plain text), login state lives in a signed session
cookie, and every task belongs to the user who created it.

Run:
    pip install -r requirements.txt
    export GOOGLE_API_KEY="your-key-here"   # or set it permanently, see README
    python web_app.py

Then open: http://127.0.0.1:5000
"""

import os
import re
import secrets
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask, request, jsonify, render_template, session,
    redirect, url_for, flash,
)
from werkzeug.security import generate_password_hash, check_password_hash

import agent  # noqa: F401  (importing builds vector_store, llm, and the graph)
import db

BASE_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# App + session configuration
# ---------------------------------------------------------------------------

def load_secret_key() -> str:
    """
    Session cookies are signed with this key. Use SECRET_KEY from the
    environment if set (recommended for deployment); otherwise generate one
    and keep it in .secret_key so logins survive a server restart.
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()

    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


flask_app = Flask(__name__)
flask_app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set SESSION_COOKIE_SECURE=1 when serving over HTTPS.
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8

# A throwaway hash so login takes the same time whether or not the email exists.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


# ---------------------------------------------------------------------------
# Brute-force protection (simple in-memory limiter)
# ---------------------------------------------------------------------------

MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60
_failed_logins = {}  # (ip, email) -> [timestamps]


def _login_key(email: str):
    return (request.remote_addr or "?", email)


def _recent_failures(key):
    cutoff = time.time() - LOCKOUT_SECONDS
    attempts = [t for t in _failed_logins.get(key, []) if t > cutoff]
    _failed_logins[key] = attempts
    return attempts


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def current_user():
    """Returns {'id', 'name', 'email'} for the logged-in user, else None."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    row = db.get_user_by_id(user_id)
    if row is None:  # account no longer exists
        session.clear()
        return None
    return {"id": row[0], "name": row[1], "email": row[2]}


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please log in to continue."}), 401
            return redirect(url_for("login"))
        return view(user, *args, **kwargs)
    return wrapper


def start_session(user_id: int):
    session.clear()  # drop anything from a previous session
    session["user_id"] = user_id
    session.permanent = True


@flask_app.after_request
def no_cache_private_pages(response):
    # Stops the browser's Back button from showing the chat after logout.
    if request.endpoint in {"index", "login", "signup"} or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Auth pages
# ---------------------------------------------------------------------------

@flask_app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect(url_for("index"))

    if request.method == "GET":
        return render_template("auth.html", mode="signup", form={}, errors={})

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    confirm = request.form.get("confirm") or ""

    errors = {}
    if not name:
        errors["name"] = "Please enter your name."
    elif len(name) > 60:
        errors["name"] = "Name is too long (60 characters max)."
    if not EMAIL_RE.match(email) or len(email) > 254:
        errors["email"] = "Please enter a valid email address."
    if len(password) < MIN_PASSWORD_LENGTH:
        errors["password"] = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    elif len(password) > 128:
        errors["password"] = "Password is too long (128 characters max)."
    if "password" not in errors and password != confirm:
        errors["confirm"] = "Passwords don't match."

    if not errors:
        user_id = db.create_user(name, email, generate_password_hash(password))
        if user_id is None:
            errors["email"] = "An account with this email already exists. Try logging in."
        else:
            start_session(user_id)
            return redirect(url_for("index"))

    form = {"name": name, "email": email}  # never echo passwords back
    return render_template("auth.html", mode="signup", form=form, errors=errors), 400


@flask_app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("index"))

    if request.method == "GET":
        return render_template("auth.html", mode="login", form={}, errors={})

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    form = {"email": email}

    key = _login_key(email)
    if len(_recent_failures(key)) >= MAX_FAILED_LOGINS:
        errors = {"form": "Too many failed attempts. Please wait a few minutes and try again."}
        return render_template("auth.html", mode="login", form=form, errors=errors), 429

    row = db.get_user_by_email(email)
    stored_hash = row[3] if row else _DUMMY_HASH
    valid = check_password_hash(stored_hash, password) and row is not None

    if not valid:
        _failed_logins.setdefault(key, []).append(time.time())
        errors = {"form": "Incorrect email or password."}
        return render_template("auth.html", mode="login", form=form, errors=errors), 401

    _failed_logins.pop(key, None)
    start_session(row[0])
    return redirect(url_for("index"))


@flask_app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You've been logged out.")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# App (login required)
# ---------------------------------------------------------------------------

@flask_app.route("/")
@login_required
def index(user):
    return render_template("index.html", user=user)


@flask_app.route("/api/chat", methods=["POST"])
@login_required
def chat(user):
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()

    if not user_input:
        return jsonify({"error": "Message cannot be empty."}), 400

    try:
        result = agent.app.invoke(
            {
                "user_input": user_input,
                "intent": "chat",
                "chat_history": [],
                "response": "",
                "user_id": user["id"],
            }
        )
        return jsonify({"intent": result["intent"], "response": result["response"]})
    except Exception as exc:  # keep the UI alive even if the LLM call fails
        return jsonify({"intent": "error", "response": str(exc)}), 500


@flask_app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks(user):
    rows = db.list_tasks(user_id=user["id"])
    tasks = [{"id": r[0], "topic": r[1], "status": r[2]} for r in rows]
    return jsonify(tasks)


@flask_app.route("/api/tasks", methods=["POST"])
@login_required
def add_task(user):
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Task topic cannot be empty."}), 400
    task_id = db.add_task(topic, user["id"])
    return jsonify({"id": task_id, "topic": topic, "status": "pending"})


@flask_app.route("/api/tasks/<int:task_id>/done", methods=["POST"])
@login_required
def complete_task(user, task_id):
    ok = db.complete_task(task_id, user["id"])
    if not ok:
        return jsonify({"error": f"No task with id {task_id}."}), 404
    return jsonify({"id": task_id, "status": "done"})


if __name__ == "__main__":
    print("\nStudyMate web UI starting at http://127.0.0.1:5000\n")
    flask_app.run(debug=True, port=5000)
