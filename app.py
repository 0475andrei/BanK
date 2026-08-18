"""
API REST (FastAPI) pentru comunicarea dintre backend si frontend.
Expune endpoint-urile de inregistrare si logare din auth.py.

Validarea structurala (campuri prezente, tipuri corecte) e facuta automat de
Pydantic. Validarile de business (CNP, lungime parola, email deja folosit
etc.) raman in auth.py, ca mesajele de eroare sa fie identice indiferent de
strat - vezi login.md pentru contractul exact al API-ului.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from auth import (
    EROARE_CNP_DUPLICAT,
    EROARE_EMAIL_DUPLICAT,
    EROARE_LOGIN_RATE_LIMIT,
    inregistreaza_user,
    logare,
)

load_dotenv()

app = FastAPI(title="BanK - Autentificare", version="1.0.0")

# In productie, inlocuieste "*" cu domeniul exact al frontend-ului.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InregistrareRequest(BaseModel):
    email: str
    parola: str
    nume: str
    prenume: str
    cnp: str
    telefon: str | None = None
    adresa: str | None = None


class LoginRequest(BaseModel):
    email: str
    parola: str


@app.exception_handler(RequestValidationError)
async def eroare_validare(request: Request, exc: RequestValidationError):
    """Cerere malformata (camp lipsa/tip gresit) - pastram acelasi format
    {success, error} ca restul API-ului, in loc de formatul implicit FastAPI."""
    return JSONResponse(status_code=400, content={"success": False, "error": "Date invalide in cererea trimisa"})


@app.exception_handler(StarletteHTTPException)
async def eroare_http(request: Request, exc: StarletteHTTPException):
    """Uniformizeaza si erorile native FastAPI (404, 405 etc.) la formatul {success, error}."""
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(exc.detail)})


@app.exception_handler(Exception)
async def eroare_neasteptata(request: Request, exc: Exception):
    """Nu lasa detalii interne (stack trace, erori DB) sa ajunga la client."""
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "A aparut o eroare interna. Incearca din nou mai tarziu."},
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/register")
def register(date: InregistrareRequest):
    rezultat = inregistreaza_user(
        email=date.email,
        parola=date.parola,
        nume=date.nume,
        prenume=date.prenume,
        cnp=date.cnp,
        telefon=date.telefon,
        adresa=date.adresa,
    )

    if rezultat["success"]:
        return JSONResponse(status_code=201, content=rezultat)

    cod_status = 409 if rezultat["error"] in (EROARE_EMAIL_DUPLICAT, EROARE_CNP_DUPLICAT) else 400
    return JSONResponse(status_code=cod_status, content=rezultat)


@app.post("/api/login")
def login(date: LoginRequest):
    if not date.email or not date.parola:
        return JSONResponse(
            status_code=400, content={"success": False, "error": "Email si parola sunt obligatorii"}
        )

    rezultat = logare(date.email, date.parola)

    if rezultat["success"]:
        return JSONResponse(status_code=200, content=rezultat)

    cod_status = 429 if rezultat["error"] == EROARE_LOGIN_RATE_LIMIT else 401
    return JSONResponse(status_code=cod_status, content=rezultat)


if __name__ == "__main__":
    import uvicorn

    reload_activ = os.environ.get("API_RELOAD", "false").lower() == "true"
    port = int(os.environ.get("API_PORT", 5000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=reload_activ)
