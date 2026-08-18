"""
Client Supabase (REST API prin HTTPS) folosit pentru accesul la baza de date.

Foloseste cheia "service_role", nu "anon"/"publishable": acest cod ruleaza
doar pe server (nu ajunge niciodata intr-un browser), deci are nevoie de acces
complet la tabele si trebuie sa ramana secret in .env (gitignored).
"""

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL / SUPABASE_KEY nu sunt setate (vezi .env.example)")

client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
