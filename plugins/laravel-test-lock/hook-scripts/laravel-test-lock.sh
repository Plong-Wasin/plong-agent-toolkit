#!/usr/bin/env bash
# One policy for Claude Code and Codex; the legacy Python hook delegates here too.
set -euo pipefail
exec python3 -B "$(dirname "${BASH_SOURCE[0]}")/laravel-test-lock-check.py"
