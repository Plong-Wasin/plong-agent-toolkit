"""Shared shell-command-text scanning helpers for the php-artisan-test hooks.

Both `laravel-test-lock-check.py` and `php-artisan-test-parallel-check.py` need
to answer the same underlying question -- "does this Bash tool_input.command
actually invoke `php artisan test`, and with what surrounding tokens?" --
without being fooled by heredoc bodies that merely *mention* the phrase in
prose (e.g. a commit message built via `git commit -m "$(cat <<'EOF' ...)"`).
This module holds that logic once so both hooks share the same, tested
understanding of "is this text really a command, or just data".
"""

from __future__ import annotations

import os
import re
import shlex

TEST_WORDS = ("php", "artisan", "test")
WRAPPER_COMMANDS = {"command", "env", "exec", "nohup", "sudo", "time"}

# Matches a heredoc opener: `<<EOF`, `<<-EOF`, `<<'EOF'`, `<<"EOF"`. Groups
# 2/3/4 give the delimiter word depending on which quoting form was used.
_HEREDOC_START_RE = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|(\S+))")

# The command word immediately before `<<` -- e.g. the `bash` in `bash <<EOF`.
_WORD_BEFORE_RE = re.compile(r"([A-Za-z0-9_./-]+)\s*$")

# Shells whose heredoc body is itself executed as shell code, so it must stay
# scannable (e.g. `bash <<'EOF'\nphp artisan test\nEOF` really does run the
# tests). Every other heredoc target (cat, tee, a plain `$(...)` capture as in
# `git commit -m "$(cat <<'EOF' ... EOF)"`) only ever treats its body as data.
_SHELL_INTERPRETERS = {"bash", "sh", "zsh", "dash", "ksh"}


def heredoc_target_is_shell(command: str, heredoc_op_start: int) -> bool:
    match = _WORD_BEFORE_RE.search(command[:heredoc_op_start].rstrip())
    return match is not None and os.path.basename(match.group(1)) in _SHELL_INTERPRETERS


def strip_heredoc_bodies(command: str) -> str:
    """Blank out heredoc bodies so their literal text is never scanned as
    shell tokens.

    A heredoc body (the lines between `<<EOF` and the closing `EOF`) is data
    piped to a command's stdin -- it is never itself parsed or executed as
    shell syntax, *unless* the heredoc is attached to a shell interpreter
    (`bash <<'EOF' ... EOF`), in which case the body really is a script and
    must stay scannable.

    Non-shell-target bodies are replaced with blank lines (not removed) so
    line numbers and any text after the heredoc in the same command stay in
    the same relative position for `shell_segments`' newline-based splitting.
    """

    result: list[str] = []
    pos = 0
    length = len(command)

    while True:
        match = _HEREDOC_START_RE.search(command, pos)
        if not match:
            result.append(command[pos:])
            break

        result.append(command[pos:match.end()])
        strip_leading_tabs = match.group(1) == "-"
        delimiter = match.group(2) or match.group(3) or match.group(4)

        body_start = command.find("\n", match.end())
        if body_start == -1:
            pos = match.end()
            continue
        body_start += 1

        terminator_start: int | None = None
        terminator_end: int | None = None
        search_from = body_start
        while True:
            line_end = command.find("\n", search_from)
            line = command[search_from: length if line_end == -1 else line_end]
            candidate = line.lstrip("\t") if strip_leading_tabs else line
            if candidate == delimiter:
                terminator_start = search_from
                terminator_end = length if line_end == -1 else line_end
                break
            if line_end == -1:
                break
            search_from = line_end + 1

        if terminator_start is None:
            # Unterminated heredoc -- leave the text as-is; the shell would
            # error on this independently, and guessing further here risks
            # hiding a real command that follows.
            pos = match.end()
            continue

        if heredoc_target_is_shell(command, match.start()):
            result.append(command[match.end():terminator_end])
        else:
            # +1 newline for the one that ends the opener line itself, which
            # counting only within [body_start, terminator_start) would
            # otherwise silently drop.
            result.append("\n" * (1 + command.count("\n", body_start, terminator_start)))
            result.append(command[terminator_start:terminator_end])
        pos = terminator_end

    return "".join(result)


def shell_segments(command: str) -> list[str]:
    """Split on unquoted shell command separators."""

    segments: list[str] = []
    segment_start = 0
    quote: str | None = None
    escaped = False

    for index, character in enumerate(command):
        if escaped:
            escaped = False
            continue

        if character == "\\" and quote != "'":
            escaped = True
            continue

        if quote is not None:
            if character == quote:
                quote = None
            continue

        if character in {"'", '"', "`"}:
            quote = character
            continue

        if character in {";", "&", "|", "\n"}:
            segments.append(command[segment_start:index])
            segment_start = index + 1

    segments.append(command[segment_start:])
    return segments


def tokenize(segment: str) -> list[str] | None:
    """`shlex.split`, or `None` if the segment doesn't tokenize cleanly."""
    try:
        return shlex.split(segment, comments=True, posix=True)
    except ValueError:
        return None


def find_test_invocations(tokens: list[str]) -> list[int]:
    """Token indices where `TEST_WORDS` occurs as three consecutive tokens."""
    return [
        index
        for index in range(len(tokens) - len(TEST_WORDS) + 1)
        if tuple(tokens[index: index + len(TEST_WORDS)]) == TEST_WORDS
    ]
