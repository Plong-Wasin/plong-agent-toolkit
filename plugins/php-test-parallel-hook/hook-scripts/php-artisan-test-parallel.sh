#!/bin/bash
# Thin wrapper kept for backward compatibility with the registered hook
# command (`bash .../php-artisan-test-parallel.sh`). All the actual logic
# lives in php-artisan-test-parallel-check.py, which shares its
# heredoc/segment-aware command scanning with laravel-test-lock-check.py
# instead of the raw-text grep this script used to do itself (that grep
# couldn't tell a real `php artisan test` invocation apart from a heredoc
# body that merely mentions the phrase in prose, and separately let a real
# unparalleled run through whenever "--parallel" appeared *anywhere* in the
# command text, even in an unrelated string).
exec /usr/bin/python3 -B "$(dirname "${BASH_SOURCE[0]}")/php-artisan-test-parallel-check.py"
