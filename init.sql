-- Script de initializare baza de date (Supabase / PostgreSQL)
-- Se ruleaza manual in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email_verified BOOLEAN DEFAULT FALSE,
    nume VARCHAR(100) NOT NULL,
    prenume VARCHAR(100) NOT NULL,
    gen VARCHAR(10),
    cnp VARCHAR(13) UNIQUE,
    data_nasterii DATE,
    telefon VARCHAR(20),
    adresa VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela pentru limitarea incercarilor gresite de login (rate limiting)
CREATE TABLE IF NOT EXISTS login_attempts (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    success BOOLEAN NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_email_created_at ON login_attempts (email, created_at);

-- Permisiuni pentru rolul service_role (folosit de backend prin SUPABASE_KEY).
-- Necesare atunci cand tabelele sunt create direct din SQL Editor, caz in
-- care nu primesc automat drepturile implicite pe care Supabase le seteaza
-- de obicei pentru tabelele create prin migratii.
GRANT SELECT, INSERT ON public.users TO service_role;
GRANT SELECT, INSERT ON public.login_attempts TO service_role;

-- Coloanele SERIAL (id) folosesc o secventa separata - INSERT are nevoie de
-- USAGE/SELECT pe ea ca sa poata genera automat urmatorul id.
GRANT USAGE, SELECT ON SEQUENCE public.users_id_seq TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.login_attempts_id_seq TO service_role;

-- Asigura ca si tabelele/secventele viitoare create in acest mod primesc drepturile necesare.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO service_role;

-- Nota: tabela otp_codes (daca a fost creata anterior pentru fluxul de
-- confirmare email prin cod OTP) nu mai este folosita de aplicatie.
-- Poate fi stearsa manual daca nu mai e nevoie de ea:
--   DROP TABLE IF EXISTS otp_codes;
