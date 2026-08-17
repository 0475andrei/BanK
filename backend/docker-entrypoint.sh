#!/usr/bin/env bash
# Runs inside the backend container. docker-compose's healthcheck on the db
# service already guarantees Postgres is accepting connections before this
# container starts, so no extra wait-loop is needed here.
set -euo pipefail

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
