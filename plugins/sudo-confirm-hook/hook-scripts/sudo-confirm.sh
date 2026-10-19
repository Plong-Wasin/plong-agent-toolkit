#!/bin/bash
# Gate any Bash command that invokes sudo behind Claude Code's native ask-permission
# prompt — every time, in every environment, whether or not sudo actually needs a
# password there:
#   - Passwordless (NOPASSWD sudoers, e.g. this devcontainer): sudo runs immediately
#     as root once you Allow. SUDO_ASKPASS below is simply never invoked.
#   - Password required + a GUI is available (zenity/kdialog/osascript): `sudo -A`
#     calls sudo-askpass.sh, which pops a native password dialog at execution time.
#   - Password required + only a real terminal is available: sudo-askpass.sh falls
#     back to reading it from /dev/tty.
# Either way, review + explicit approve/deny always happens first.
INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$CMD" ]; then
  echo '{}'
  exit 0
fi

# Matches sudo as a command word right after a shell operator (or string start),
# optionally preceded by inline env-var assignments (e.g. "FOO=1 sudo ...") so those
# can't be used to slip a sudo call past detection. Deliberately anchored so plain
# path/text references like "/usr/bin/sudo" or "/etc/sudoers" never match.
SUDO_PATTERN='(^|&&|\|\||;|\||\$\()([[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*)sudo\b'

if echo "$CMD" | grep -Eq "$SUDO_PATTERN"; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  ASKPASS_SCRIPT="$SCRIPT_DIR/sudo-askpass.sh"

  if echo "$CMD" | grep -q 'SUDO_ASKPASS'; then
    NEW_CMD="$CMD"
  else
    NEW_CMD=$(echo "$CMD" | sed -E "s#${SUDO_PATTERN}#\1\2SUDO_ASKPASS='${ASKPASS_SCRIPT}' sudo -A#g")
  fi

  jq -n --arg cmd "$NEW_CMD" --arg orig "$CMD" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: ("This command uses sudo:\n\n  " + $orig + "\n\nReview it before allowing. If this environment has passwordless sudo, it runs immediately as root on Allow. If a password is actually required here, sudo will prompt for it via a GUI or terminal dialog at execution time."),
      updatedInput: {command: $cmd}
    }
  }'
else
  echo '{}'
fi
