"""
SQLite store for StudyMate: users (for sign in / sign up) and study tasks.
The agent and the web app both read/write through this module.

Tasks belong to a user (tasks.user_id). Passing user_id=None means "no user",
which is what the command-line version (`python agent.py`) uses.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "studymate.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER REFERENCES users(id)
        )
        """
    )

    # Migration: databases created before sign-in existed have no user_id column.
    columns = [row[1] for row in conn.execute("PRAGMA table_info(tasks)")]
    if "user_id" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN user_id INTEGER REFERENCES users(id)")

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(name: str, email: str, password_hash: str):
    """Create a user. Returns the new user id, or None if the email is taken."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_by_email(email: str):
    """Returns (id, name, email, password_hash) or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id, name, email, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    return row


def get_user_by_id(user_id: int):
    """Returns (id, name, email) or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id, name, email FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# Tasks (scoped to a user)
# ---------------------------------------------------------------------------

def add_task(topic: str, user_id: int = None) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO tasks (topic, user_id) VALUES (?, ?)", (topic, user_id)
    )
    conn.commit()
    task_id = cur.lastrowid
    conn.close()
    return task_id


def complete_task(task_id: int, user_id: int = None) -> bool:
    """Marks a task done — only if it belongs to this user."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE tasks SET status = 'done' WHERE id = ? AND user_id IS ?",
        (task_id, user_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def list_tasks(status: str = None, user_id: int = None):
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT id, topic, status FROM tasks "
            "WHERE user_id IS ? AND status = ? ORDER BY id",
            (user_id, status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, topic, status FROM tasks WHERE user_id IS ? ORDER BY id",
            (user_id,),
        ).fetchall()
    conn.close()
    return rows
