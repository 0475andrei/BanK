#!/usr/bin/env bash
# Runs inside the backend container. No local database to wait for or
# migrate - the schema lives in Supabase, applied via
# backend/supabase/migrations/*.sql pasted into the Supabase SQL Editor.
set -euo pipefail

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
