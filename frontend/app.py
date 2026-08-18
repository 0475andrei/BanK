"""Minimal Flask starter for whoever builds the real frontend.

Auth pattern this assumes (see README.md for the full reasoning): the
browser calls the FastAPI backend DIRECTLY for anything that needs the
session cookie (login, accounts, transfers, ...), using `fetch` with
`credentials: "include"`. Flask here only serves page structure and static
assets - it never proxies API calls server-side, so it never has to touch
the session cookie itself. That's why there's no `requests` dependency and
no server-side session handling.
"""

import os

from dotenv import load_dotenv
from flask import Flask, render_template

load_dotenv()

API_BASE_URL = os.environ.get("BACKEND_API_BASE_URL", "http://localhost:8000/api/v1")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")


@app.context_processor
def inject_api_base_url():
    """Makes {{ api_base_url }} available in every template - see
    templates/base.html's apiFetch() helper."""
    return {"api_base_url": API_BASE_URL}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/login")
def login():
    return render_template("login.html")


@app.get("/accounts")
def accounts():
    return render_template("accounts.html")


@app.get("/transfers")
def transfers():
    return render_template("transfers.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
