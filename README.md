# StudyMate — AI Study Planning Agent

A small autonomous agent built with **LangGraph** (multi-step task routing/planning)
and **LangChain** (RAG + tool use), backed by a **SQLite** database and a **FAISS**
vector store, with **Google Gemini** (free tier) as the reasoning LLM.

This is a standalone project — not tied to any other project — built specifically
to demonstrate the agentic AI / RAG skill set (LangChain, LangGraph, vector DBs,
SQL, prompt engineering) independent of web/database work.

## What it does
- **Answers study questions** by retrieving relevant chunks from your notes with
  FAISS + HuggingFace embeddings (RAG), then asking Gemini to answer using only
  that retrieved context.
- **Manages a task list** (add / complete / list study topics) in a SQLite
  database — the LLM decides which action to take, and the agent actually
  executes it (a minimal but real example of LLM tool-use).
- **Routes each message** through a LangGraph `StateGraph` with a classification
  node that decides whether to answer from notes, manage a task, or just chat —
  this is the "agent logic / task planning" piece.

## Setup (about 10–15 minutes)
1. Python 3.10+.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Get a free Google Gemini API key from https://aistudio.google.com/apikey
   (just needs a Google account, no card/billing required) and set it:
   ```
   export GOOGLE_API_KEY="your-key-here"        # macOS/Linux
   setx GOOGLE_API_KEY "your-key-here"           # Windows (new terminal after this)
   ```
   Or, for the current PowerShell session only:
   ```
   $env:GOOGLE_API_KEY="your-key-here"
   ```
4. Run:
   ```
   python agent.py
   ```
5. Try:
   - "What's the time complexity of a hash map lookup?"
   - "Add a task to revise linked lists"
   - "List my tasks"
   - "Mark task 1 as done"

## Web UI (optional)
There's also a browser-based interface — a chat panel plus a live task
sidebar — built with Flask, on top of the exact same agent logic.

```
python web_app.py
```

Then open **http://127.0.0.1:5000** in your browser. Leave the terminal
running while you use it; press Ctrl+C there to stop the server.

The interface follows a ChatGPT-style layout: collapsible sidebar with the task list,
a centered chat thread with Markdown and copyable code blocks, and a light/dark theme
toggle (top right). The theme choice is saved in the browser, and the first visit
follows your OS setting. Markdown and DOMPurify load from a CDN, so the first load
needs internet access.

The web UI and the CLI (`python agent.py`) both use the same `agent.py` and
`db.py` underneath. Web tasks belong to the logged-in account, while the CLI
keeps its own separate, account-less task list.

### Accounts (sign up, log in, log out)
- Open the site and you land on the **login** page. New here? Choose
  **Create an account** (name, email, password of 8+ characters).
- Your tasks are private to your account — the chat agent's "add / list / mark
  done" actions only ever touch your own tasks.
- **Log out** is at the bottom of the sidebar, under your name.
- Passwords are stored hashed (never in plain text). Sessions last 14 days, and
  5 failed logins for the same email/IP trigger a 15-minute lockout.
- Login sessions are signed with a secret key. By default one is generated into
  `.secret_key` on first run (keep that file private, don't share or commit it).
  For deployment, set `SECRET_KEY` in the environment instead, and set
  `SESSION_COOKIE_SECURE=1` when serving over HTTPS.
- Upgrading from the earlier version? Your existing `studymate.db` is upgraded
  automatically. Tasks created before accounts existed stay visible only to the
  CLI.

## What this demonstrates (for interviews)
- **LangGraph**: a `StateGraph` with a routing/classification node and multiple
  branches — the core idea behind agent task planning.
- **LangChain**: document loading, chunking, embeddings, FAISS retrieval.
- **RAG**: grounding LLM answers strictly in retrieved context.
- **SQL + agents**: the LLM decides an action, the agent executes real SQL
  (SQLite) reads/writes — a simple version of "agents fetching and reasoning
  over data."
- **Memory**: conversation history is threaded through agent state across turns.
- **Prompt engineering**: structured prompts to get reliable, parseable output
  (e.g., the `ACTION|VALUE` format for task management).

## Extend it further
- Swap SQLite for Postgres/MySQL for a closer match to production systems.
- Add a second LangGraph node for multi-turn task planning (e.g., break a topic
  into a study schedule across several days).
- Add LangGraph persistence (checkpointing) for durable long-term memory.
- The web UI (`web_app.py`) is a thin Flask layer — deploy it, or add features
  like password reset, email verification, or more API endpoints.
