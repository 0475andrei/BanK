# Backend Autentificare — Documentatie pentru Frontend

Acest document descrie API-ul REST expus de backend pentru inregistrare si
logare, ca sa poata fi integrat cu un frontend (web/mobil).

## Cum pornesti backend-ul

```
pip install -r requirements.txt
python app.py
```

Serverul porneste implicit pe `http://localhost:5000` (portul e configurabil
din `.env` cu `FLASK_PORT`). Toate rutele API sunt sub prefixul `/api`.

CORS e activat pe `/api/*` pentru orice origine (potrivit pentru dezvoltare
locala). Cand exista un domeniu de productie pentru frontend, backend-ul
trebuie restrictionat sa accepte cereri doar de acolo (vezi comentariul din
`app.py`).

Toate cererile si raspunsurile sunt JSON (`Content-Type: application/json`).

---

## `GET /api/health`

Verificare rapida ca serverul ruleaza. Nu necesita autentificare.

**Raspuns `200`:**
```json
{ "status": "ok" }
```

---

## `POST /api/register`

Creeaza un cont nou.

**Body cerere:**
```json
{
  "email": "ion.popescu@exemplu.com",
  "parola": "ParolaMea123",
  "nume": "Popescu",
  "prenume": "Ion",
  "cnp": "1234567890123",
  "telefon": "0712345678",
  "adresa": "Str. Exemplu nr. 1"
}
```

| Camp | Obligatoriu | Observatii |
|---|---|---|
| `email` | da | trebuie sa fie o adresa valida |
| `parola` | da | minim 8 caractere |
| `nume` | da | |
| `prenume` | da | |
| `cnp` | da | 13 cifre, validat cu algoritmul oficial (cifra de control MOD 11); gen si data nasterii se **deduc automat** din CNP, nu trebuie trimise separat |
| `telefon` | nu | poate lipsi sau fi `null` |
| `adresa` | nu | poate lipsi sau fi `null` |

**Raspuns succes `201`:**
```json
{ "success": true, "mesaj": "Cont creat cu succes" }
```

**Raspunsuri eroare:**

| HTTP | Cand apare | Exemplu `error` |
|---|---|---|
| `400` | date invalide (email/parola/CNP/nume/prenume) | `"Adresa de email nu este valida"`, `"Parola trebuie sa aiba cel putin 8 caractere"`, `"Numele si prenumele sunt obligatorii"`, sau un motiv specific de CNP invalid (ex: `"Luna nasterii din CNP este invalida"`, `"Cifra de control a CNP-ului este invalida"`) |
| `409` | emailul sau CNP-ul exista deja in baza de date | `"Exista deja un cont cu acest email"` / `"Exista deja un cont asociat acestui CNP"` |

Toate raspunsurile de eroare au forma:
```json
{ "success": false, "error": "mesajul de eroare" }
```

**Notes pentru frontend:**
- Mesajele de eroare la CNP sunt intentionat specifice (ajuta userul sa corecteze), spre deosebire de login unde sunt generice.
- Nu exista inca flux de confirmare a emailului (nu mai e OTP) — contul e activ imediat dupa inregistrare, se poate loga direct.

---

## `POST /api/login`

Autentifica un utilizator existent.

**Body cerere:**
```json
{
  "email": "ion.popescu@exemplu.com",
  "parola": "ParolaMea123"
}
```

**Raspuns succes `200`:**
```json
{
  "success": true,
  "user": { "id": 1, "nume": "Popescu", "prenume": "Ion" }
}
```
Nu se returneaza parola/hash-ul sau alte date sensibile (CNP, telefon, adresa).

**Raspunsuri eroare:**

| HTTP | Cand apare | `error` |
|---|---|---|
| `400` | lipseste `email` sau `parola` din body | `"Email si parola sunt obligatorii"` |
| `401` | email inexistent SAU parola gresita | `"Email sau parola incorecta"` (mesaj **generic** — intentionat, nu se specifica daca emailul exista, pentru a preveni enumerarea conturilor) |
| `429` | 5 incercari esuate consecutive pentru acel email in ultimele 15 minute | `"Prea multe incercari esuate. Incearca din nou mai tarziu."` |

**Notes pentru frontend:**
- Nu incerca sa deosebesti "email gresit" de "parola gresita" in UI — backend-ul da mereu acelasi mesaj `401`, deci arata-l ca atare userului.
- La `429`, arata userului mesajul primit si eventual dezactiveaza temporar butonul de login — nu mai reincerca automat.
- Nu exista inca sesiune/token (JWT, cookie) — raspunsul de succes doar confirma autentificarea si da datele de baza ale userului. Daca frontend-ul are nevoie sa retina "userul e logat" intre request-uri, e nevoie de un mecanism de sesiune care inca nu e implementat in acest modul.

---

## Erori generale (orice endpoint)

| HTTP | Cand | `error` |
|---|---|---|
| `500` | eroare interna neasteptata (ex: Supabase indisponibil) | `"A aparut o eroare interna. Incearca din nou mai tarziu."` — mesaj generic, fara detalii tehnice |
| `404` | ruta nu exista | pagina HTML standard Flask (nu JSON) |

---

## Ce lipseste inca (de avut in vedere pentru frontend)

- **Sesiune/autentificare persistenta**: dupa login, nu se emite niciun token/cookie. Orice ecran care are nevoie sa stie "cine e userul logat" dupa reincarcarea paginii va avea nevoie de un mecanism suplimentar (nu exista inca in backend).
- **Confirmare email**: fluxul initial cu cod OTP a fost eliminat — conturile sunt active imediat dupa `/api/register`.
- **Reset parola**: nu exista endpoint pentru asta momentan.
