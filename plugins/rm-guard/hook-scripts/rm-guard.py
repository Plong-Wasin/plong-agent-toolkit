#!/usr/bin/env python3
"""PreToolUse hook: send back `rm` and `rmdir` commands whose path contains an unguarded shell variable.

Claude Code stops such a command with a prompt that only a person can answer, and an unattended session waits
until the prompt times out. This hook runs first, answers in the model's own channel with how to write the
command so it passes, and lets the session continue. It never blocks on its own failure (it exits 0 silently).
"""
import json
import re
import shlex
import sys

# A variable that is not written as ${NAME:?...}: $NAME, ${NAME}, ${NAME:-x}, $(command).
UNGUARDED = re.compile(r"\$(?:\(|\{(?![A-Za-z_][A-Za-z0-9_]*:\?)|[A-Za-z_])")
SEPARATORS = re.compile(r"&&|\|\||[;|\n]")
REMOVERS = {"rm", "rmdir"}
# Words that can stand in front of a command inside a compound command: `for ...; do rm ...; done`.
PREFIXES = {"do", "then", "else", "elif", "if", "while", "until", "time", "sudo", "command", "exec", "!"}

REASON = (
    "This delete command has a path built from a shell variable that may be empty, and Claude Code stops such "
    "commands with a prompt that nobody answers in an unattended session. Write the path literally, or guard "
    'each variable as "${NAME:?}" (for example rm -f "${DIR:?}/node_modules"). To remove a temporary git '
    "worktree, use git worktree remove instead of rm."
)


def flagged(command: str) -> bool:
    for segment in SEPARATORS.split(command):
        text = segment.strip().lstrip("({ ").strip()
        try:
            words = shlex.split(text, posix=False)
        except ValueError:
            words = text.split()
        while words and words[0] in PREFIXES:
            words = words[1:]
        if not words or words[0] not in REMOVERS:
            continue
        if any(UNGUARDED.search(word) for word in words[1:]):
            return True
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") != "Bash":
            return 0
        command = (payload.get("tool_input") or {}).get("command", "")
        if not isinstance(command, str) or not flagged(command):
            return 0
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": REASON}}, sys.stdout)
        return 0
    except Exception:  # a broken guard must never stop work
        return 0


if __name__ == "__main__":
    sys.exit(main())
