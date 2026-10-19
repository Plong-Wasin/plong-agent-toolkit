#!/usr/bin/env python3
"""Require a host-side lock around local or Docker-based PHP test commands.

This scans common shell/exec forms, rather than implementing a shell interpreter.
Use the runner around the complete Docker command so containers need no flock.
"""

import json
import os
from pathlib import Path
import re
import shlex
import sys

from _shell_command_scan import shell_segments, strip_heredoc_bodies, tokenize


RUNNER = Path(__file__).with_name("laravel-test-lock-run.sh").resolve()
LOCK_FILE = os.environ.get("CLAUDE_TEST_LOCK") or "/tmp/php-artisan-test.lock"
SHELLS = {"bash", "sh", "dash", "zsh", "ksh"}
TEST_BINS = {"phpunit", "paratest", "pest"}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def skip_options(tokens, value_options):
    """Return arguments after leading options, respecting options with values."""
    index = 0
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index]
        index += 1
        if option == "--":
            break
        if option in value_options:
            index += 1
    return tokens[index:]


def shell_script(tokens):
    for index, token in enumerate(tokens):
        if token.startswith("-") and "c" in token[1:] and not token.startswith("--"):
            return tokens[index + 1] if index + 1 < len(tokens) else ""
    return None


def has_unlocked_test(command, locked=False, depth=0, in_container=False):
    if depth > 32:
        raise ValueError("shell nesting exceeds hook scan limit")
    if isinstance(command, list):
        return scan_tokens(command, locked, depth + 1, in_container)
    for segment in shell_segments(strip_heredoc_bodies(command)):
        tokens = tokenize(segment)
        if tokens is None:
            if re.search(r"\bartisan\s+test\b|\b(?:phpunit|paratest|pest)\b", segment) and not locked:
                return True
        elif scan_tokens(tokens, locked, depth + 1, in_container):
            return True
    return False


def scan_tokens(tokens, locked, depth, in_container=False):
    if depth > 32:
        raise ValueError("shell nesting exceeds hook scan limit")
    tokens = list(tokens)
    while tokens and (ASSIGNMENT.match(tokens[0]) or tokens[0] in {"!", "then", "do", "if", "while"}):
        tokens.pop(0)
    if not tokens:
        return False
    executable = os.path.basename(tokens[0])
    args = tokens[1:]

    if executable in {"env", "sudo", "command", "exec", "nohup", "time"}:
        args = skip_options(args, {"-u", "--user", "-g", "--group", "-C", "--chdir", "--unset"})
        return scan_tokens(args, locked, depth + 1, in_container)

    if Path(os.path.expandvars(tokens[0])).resolve() == RUNNER:
        # Runner owns the lock for the complete child shell, including Docker.
        return has_unlocked_test(args[0], locked, depth + 1, in_container) if in_container and args else False

    if executable in SHELLS:
        script = shell_script(args)
        if script is not None:
            return has_unlocked_test(script, locked, depth + 1, in_container)
        args = skip_options(args, {"--rcfile", "--init-file"})
        if args and Path(os.path.expandvars(args[0])).resolve() == RUNNER:
            return has_unlocked_test(args[1], locked, depth + 1, in_container) if in_container and len(args) > 1 else False
        return False  # Other script files aren't read or executed by this hook.

    if executable == "flock":
        args = skip_options(args, {"-w", "--wait", "--timeout", "-E", "--conflict-exit-code"})
        exclusive = not any(option in {"-s", "--shared", "-u", "--unlock"} for option in tokens[1:])
        if args:
            owns_lock = not in_container and exclusive and os.path.abspath(args[0]) == os.path.abspath(LOCK_FILE)
            child = args[1:]
            if child[:1] in (["-c"], ["--command"]):
                return has_unlocked_test(" ".join(child[1:]), locked or owns_lock, depth + 1, in_container)
            return scan_tokens(child, locked or owns_lock, depth + 1, in_container)
        return False

    if executable in {"docker", "docker-compose"}:
        if executable == "docker":
            args = skip_options(args, {"--context", "-c", "--host", "-H", "--config"})
            if args[:1] == ["compose"]:
                args = args[1:]
        args = skip_options(args, {"-p", "--project-name", "-f", "--file", "--env-file", "--profile", "--project-directory", "--parallel"})
        if not args or args[0] not in {"exec", "run"}:
            return False
        args = skip_options(args[1:], {
            "-e", "--env", "--env-file", "-w", "--workdir", "-u", "--user",
            "--entrypoint", "--network", "--name", "-v", "--volume", "--mount",
            "-p", "--publish", "--cpus", "-m", "--memory", "--index", "--cap-add",
            "--hostname", "--add-host", "--device", "--pull", "--restart",
        })
        # The next token is the container, compose service, or image name.
        # Host lock state is deliberately retained across this Docker boundary.
        return scan_tokens(args[1:], locked, depth + 1, True) if args else False

    if executable == "php" or re.fullmatch(r"php\d+(?:\.\d+)?", executable):
        return scan_tokens(skip_options(args, {"-d", "-c", "--define", "--php-ini"}), locked, depth + 1, in_container)
    if executable in TEST_BINS or (executable == "artisan" and args[:1] == ["test"]):
        return not locked
    return False


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be an object")
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if command is None:
            return 0
        if not isinstance(command, (str, list)) or (isinstance(command, list) and not all(isinstance(x, str) for x in command)):
            raise ValueError("command must be a string or argv array")
        if has_unlocked_test(command):
            shell_command = shlex.join(command) if isinstance(command, list) else command
            wrapped = shlex.join(["bash", str(RUNNER), shell_command])
            print(
                "Test runs must hold the shared host lock. Re-run through the runner "
                "(it waits in line; Docker needs no flock inside the container):\n\n" + wrapped,
                file=sys.stderr,
            )
            return 2
    except (ValueError, TypeError, OSError) as error:
        print(f"laravel-test-lock: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
