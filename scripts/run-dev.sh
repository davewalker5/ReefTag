#!/usr/bin/env bash

export PROJECT_ROOT=$( cd "$(dirname "$0")/.." ; pwd -P )
cd "$PROJECT_ROOT"

. venv/bin/activate

export REEFTAG_DB_PATH="$PROJECT_ROOT/data/reeftag.db"
exec python -m reef_tag "$@"
