#!/usr/bin/env python3
"""Block `php artisan test` Bash calls that omit --parallel.

Nudges the agent to always pass --parallel --processes=<n> itself instead of
relying on the hook to silently rewrite the command. Shares its
heredoc/segment-aware scanning with laravel-test-lock-check.py (see
_shell_command_scan.py) so a command is only ever judged by what it actually
runs -- never by unrelated prose elsewhere in the same Bash call that happens
to mention "php artisan test" or "--parallel".
"""

from __future__ import annotations

import json
import math
import os
import shlex
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _shell_command_scan import (  # noqa: E402
    find_test_invocations,
    shell_segments,
    strip_heredoc_bodies,
    tokenize,
)


def read_hook_input() -> dict[str, Any]:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    return payload


def segment_has_parallel_flag(segment: str, tokens: list[str] | None) -> bool:
    if tokens is not None:
        return any(token == "--parallel" or token.startswith("--parallel=") for token in tokens)
    return "--parallel" in segment


def segment_runs_test_without_parallel(segment: str) -> bool:
    tokens = tokenize(segment)

    if tokens is not None and find_test_invocations(tokens):
        return not segment_has_parallel_flag(segment, tokens)

    # Nested shell invocations such as `bash -lc 'php artisan test'` don't
    # tokenize the inner command as separate top-level tokens. Scoped to this
    # one segment's own text (never the whole raw command), so a --parallel
    # mention in a *different* segment can't paper over an unparalleled run.
    if "php artisan test" in segment:
        return "--parallel" not in segment

    return False


def recommended_processes() -> int:
    cpu_count = os.cpu_count() or 1
    return max(1, math.ceil(cpu_count / 2))


def deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def main() -> int:
    try:
        payload = read_hook_input()
    except (json.JSONDecodeError, ValueError, TypeError) as error:
        print(f"php-artisan-test-parallel-check hook could not read input: {error}", file=sys.stderr)
        return 2

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    # Codex can supply an argv array rather than a shell command string.
    if isinstance(command, list) and all(isinstance(part, str) for part in command):
        command = shlex.join(command)
    if not isinstance(command, str):
        return 0

    command = strip_heredoc_bodies(command)

    if any(segment_runs_test_without_parallel(segment) for segment in shell_segments(command)):
        processes = recommended_processes()
        deny(
            "Blocked: this project always runs tests in parallel. Re-run with "
            f"--parallel --processes={processes} (half of available CPU cores)."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
