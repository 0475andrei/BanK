#!/usr/bin/env bash
# One-command startup: from a clean checkout, this brings up Postgres + the
# API, running migrations automatically (see docker-entrypoint.sh).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

docker compose up --build
