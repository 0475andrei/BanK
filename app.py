"""
API REST (Flask) pentru comunicarea dintre backend si frontend.
Expune endpoint-urile de inregistrare si logare din auth.py.
"""

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from auth import (
    EROARE_CNP_DUPLICAT,
    EROARE_EMAIL_DUPLICAT,
    EROARE_LOGIN_RATE_LIMIT,
    inregistreaza_user,
    logare,
)

load_dotenv()

app = Flask(__name__)

# In productie, inlocuieste "*" cu domeniul exact al frontend-ului
# (ex: CORS(app, origins=["https://exemplu.com"])).
CORS(app, resources={r"/api/*": {"origins": "*"}})


@app.errorhandler(Exception)
def trateaza_eroare_neasteptata(eroare):
    """Nu lasa detalii interne (stack trace, erori DB) sa ajunga la client."""
    if isinstance(eroare, HTTPException):
        return eroare
    app.logger.exception("Eroare neasteptata")
    return jsonify({"success": False, "error": "A aparut o eroare interna. Incearca din nou mai tarziu."}), 500


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/register", methods=["POST"])
def register():
    date = request.get_json(silent=True) or {}

    rezultat = inregistreaza_user(
        email=date.get("email", ""),
        parola=date.get("parola", ""),
        nume=date.get("nume", ""),
        prenume=date.get("prenume", ""),
        cnp=date.get("cnp", ""),
        telefon=date.get("telefon"),
        adresa=date.get("adresa"),
    )

    if rezultat["success"]:
        return jsonify(rezultat), 201

    cod_status = 409 if rezultat["error"] in (EROARE_EMAIL_DUPLICAT, EROARE_CNP_DUPLICAT) else 400
    return jsonify(rezultat), cod_status


@app.route("/api/login", methods=["POST"])
def login():
    date = request.get_json(silent=True) or {}
    email = date.get("email", "")
    parola = date.get("parola", "")

    if not email or not parola:
        return jsonify({"success": False, "error": "Email si parola sunt obligatorii"}), 400

    rezultat = logare(email, parola)

    if rezultat["success"]:
        return jsonify(rezultat), 200

    cod_status = 429 if rezultat["error"] == EROARE_LOGIN_RATE_LIMIT else 401
    return jsonify(rezultat), cod_status


if __name__ == "__main__":
    debug_activ = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    port = int(os.environ.get("FLASK_PORT", 5000))
    app.run(debug=debug_activ, port=port)
