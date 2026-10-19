#!/usr/bin/env bash
# Run "$1" while holding the machine-wide Laravel test lock; waits in line if busy.
set -euo pipefail

# Keep the original PHP hook's path so old explicit flock commands share the queue.
lock="${CLAUDE_TEST_LOCK:-/tmp/php-artisan-test.lock}"
info="$lock.holder"

if [ "$#" -ne 1 ]; then
  echo 'Usage: laravel-test-lock-run.sh "shell command"' >&2
  exit 2
fi

exec 9>"$lock"
if ! flock -n 9; then
  echo "[test-lock] another test run holds the lock: $(cat "$info" 2>/dev/null || echo unknown). Waiting..." >&2
  start=$(date +%s)
  flock 9
  echo "[test-lock] acquired after $(( $(date +%s) - start ))s" >&2
fi
printf 'pid=%s since=%s cwd=%s\n' "$$" "$(date '+%F %T')" "$PWD" >"$info"

# Close fd 9 in the child so nothing it spawns can keep the lock alive.
if bash -c "$1" 9>&-; then
  status=0
else
  status=$?
fi
: >"$info"
exit "$status"
