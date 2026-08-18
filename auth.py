"""
Logica de autentificare: inregistrare si logare, prin Supabase REST API.
Nicio parola in clar nu ajunge in baza de date sau in loguri.
"""

import re
from datetime import datetime, timedelta, timezone

import bcrypt
from postgrest.exceptions import APIError

from db import client
from validare import extrage_data_nasterii, extrage_gen, valideaza_cnp

# --- Constante de configurare ---

PAROLA_LUNGIME_MINIMA = 8
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LOGIN_MAX_INCERCARI_ESUATE = 5
LOGIN_FEREASTRA_BLOCARE_MINUTE = 15

EROARE_LOGIN_GENERICA = "Email sau parola incorecta"
EROARE_LOGIN_RATE_LIMIT = "Prea multe incercari esuate. Incearca din nou mai tarziu."
EROARE_EMAIL_DUPLICAT = "Exista deja un cont cu acest email"
EROARE_CNP_DUPLICAT = "Exista deja un cont asociat acestui CNP"

COD_EROARE_UNIQUE_VIOLATION = "23505"


# --- Hash parola (bcrypt) ---


def hash_parola(parola: str) -> str:
    """Genereaza un hash bcrypt pentru parola data. Parola in clar nu e retinuta nicaieri."""
    return bcrypt.hashpw(parola.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verifica_parola(parola: str, parola_hash: str) -> bool:
    """Verifica o parola in clar fata de hash-ul bcrypt salvat."""
    return bcrypt.checkpw(parola.encode("utf-8"), parola_hash.encode("utf-8"))


# --- Inregistrare ---


def inregistreaza_user(
    email: str,
    parola: str,
    nume: str,
    prenume: str,
    cnp: str,
    gen: str | None = None,
    data_nasterii=None,
    telefon: str | None = None,
    adresa: str | None = None,
) -> dict:
    """
    Inregistreaza un utilizator nou. Valideaza CNP-ul, hash-uieste parola
    si salveaza userul in tabela `users`.
    """
    if not email or not EMAIL_REGEX.match(email.strip()):
        return {"success": False, "error": "Adresa de email nu este valida"}

    email = email.strip().lower()

    if not parola or len(parola) < PAROLA_LUNGIME_MINIMA:
        return {
            "success": False,
            "error": f"Parola trebuie sa aiba cel putin {PAROLA_LUNGIME_MINIMA} caractere",
        }

    if not nume or not nume.strip() or not prenume or not prenume.strip():
        return {"success": False, "error": "Numele si prenumele sunt obligatorii"}

    cnp_valid, motiv_eroare_cnp = valideaza_cnp(cnp)
    if not cnp_valid:
        return {"success": False, "error": motiv_eroare_cnp}

    if gen is None:
        gen = extrage_gen(cnp)
    if data_nasterii is None:
        data_nasterii = extrage_data_nasterii(cnp)

    parola_hash = hash_parola(parola)

    try:
        client.table("users").insert(
            {
                "email": email,
                "password_hash": parola_hash,
                "nume": nume.strip(),
                "prenume": prenume.strip(),
                "gen": gen,
                "cnp": cnp,
                "data_nasterii": data_nasterii.isoformat(),
                "telefon": telefon,
                "adresa": adresa,
            }
        ).execute()
    except APIError as eroare:
        if eroare.code == COD_EROARE_UNIQUE_VIOLATION:
            if "cnp" in (eroare.message or "").lower():
                return {"success": False, "error": EROARE_CNP_DUPLICAT}
            return {"success": False, "error": EROARE_EMAIL_DUPLICAT}
        raise

    return {"success": True, "mesaj": "Cont creat cu succes"}


# --- Logare ---


def _numar_incercari_esuate(email: str) -> int:
    prag_timp = (
        datetime.now(timezone.utc) - timedelta(minutes=LOGIN_FEREASTRA_BLOCARE_MINUTE)
    ).isoformat()
    raspuns = (
        client.table("login_attempts")
        .select("id", count="exact")
        .eq("email", email)
        .eq("success", False)
        .gte("created_at", prag_timp)
        .execute()
    )
    return raspuns.count or 0


def _inregistreaza_incercare_login(email: str, success: bool) -> None:
    client.table("login_attempts").insert({"email": email, "success": success}).execute()


def logare(email: str, parola: str) -> dict:
    """
    Autentifica un utilizator prin email si parola.
    Mesajele de eroare sunt intentionat generice pentru a preveni enumerarea
    conturilor existente (nu se specifica daca emailul exista sau parola e gresita).
    """
    email = email.strip().lower()

    if _numar_incercari_esuate(email) >= LOGIN_MAX_INCERCARI_ESUATE:
        return {"success": False, "error": EROARE_LOGIN_RATE_LIMIT}

    raspuns = (
        client.table("users")
        .select("id, password_hash, nume, prenume")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    utilizatori = raspuns.data

    if not utilizatori:
        _inregistreaza_incercare_login(email, False)
        return {"success": False, "error": EROARE_LOGIN_GENERICA}

    user = utilizatori[0]

    if not verifica_parola(parola, user["password_hash"]):
        _inregistreaza_incercare_login(email, False)
        return {"success": False, "error": EROARE_LOGIN_GENERICA}

    _inregistreaza_incercare_login(email, True)

    return {
        "success": True,
        "user": {"id": user["id"], "nume": user["nume"], "prenume": user["prenume"]},
    }
