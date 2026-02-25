#!/usr/bin/env bash
# Run the auditor using the project environment (uv). Use this so dependencies are found.
cd "$(dirname "$0")"
exec uv run python -m src.run_audit "$@"
