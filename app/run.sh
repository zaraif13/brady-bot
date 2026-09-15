#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
uvicorn brady_bot.api:app --reload --port 8000
