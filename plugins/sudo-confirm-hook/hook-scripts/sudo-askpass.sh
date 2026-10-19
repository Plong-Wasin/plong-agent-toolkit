#!/bin/bash
# SUDO_ASKPASS helper: called by `sudo -A` only when sudo actually needs a password
# and has no cached credential. Tries whatever prompt mechanism this environment
# has, in order: GUI dialog, then a real terminal. If none exist, fails loudly
# instead of hanging.
PROMPT="sudo password"

if command -v zenity >/dev/null 2>&1; then
  zenity --password --title="$PROMPT" 2>/dev/null
  exit $?
fi

if command -v kdialog >/dev/null 2>&1; then
  kdialog --password "$PROMPT:" 2>/dev/null
  exit $?
fi

if command -v osascript >/dev/null 2>&1; then
  osascript -e "display dialog \"$PROMPT:\" default answer \"\" with hidden answer" \
            -e "text returned of result" 2>/dev/null
  exit $?
fi

# /dev/tty can have world-readable/writable permission bits even when there is no
# controlling terminal for this process (ENXIO on open) — actually try opening it
# rather than trusting `-r`/`-w`, or a missing TTY silently yields an empty password.
if ( : < /dev/tty ) 2>/dev/null; then
  read -r -s -p "$PROMPT: " pw < /dev/tty 2>/dev/tty
  RC=$?
  echo >&2
  if [ $RC -eq 0 ]; then
    printf '%s\n' "$pw"
    exit 0
  fi
fi

echo "sudo-askpass: no password prompt available (no zenity/kdialog/osascript/tty)" >&2
exit 1
