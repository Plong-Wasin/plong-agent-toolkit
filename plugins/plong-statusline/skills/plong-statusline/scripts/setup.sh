#!/bin/bash
# Install (or remove) the plong statusline: model + effort, directory, git
# branch, context window, and the 5-hour / weekly plan usage.
#
#   setup.sh install    point Claude Code's statusline at it (safe to re-run)
#   setup.sh uninstall  restore the statusline command that was there before
#   setup.sh status     show what is installed
#   setup.sh refresh    re-copy the script if installed (run by the SessionStart
#                       hook so plugin updates reach the installed copy); silent
#
# If the usage-guard-statusline wrapper owns statusLine.command, this script is
# installed as the wrapper's inner statusline instead, so both keep working.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$SKILL_DIR/scripts/statusline.sh"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/plong-statusline"
TARGET="$STATE_DIR/statusline.sh"
PROFILE_KEY=$(printf '%s' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" | cksum | cut -d' ' -f1)
# The script is shared; what it replaced is remembered per profile.
PREVIOUS="$STATE_DIR/previous-command.$PROFILE_KEY"
CMD="bash $TARGET"
SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
GUARD_STATE="${XDG_DATA_HOME:-$HOME/.local/share}/claude-usage-guard"
GUARD_INNER="$GUARD_STATE/inner-statusline.$PROFILE_KEY"
GUARD_LEGACY_INNER="$GUARD_STATE/inner-statusline"

guard_inner_cmd() { cat "$GUARD_INNER" 2>/dev/null || cat "$GUARD_LEGACY_INNER" 2>/dev/null || true; }

current_cmd() {
  [ -f "$SETTINGS" ] || { echo ""; return; }
  jq -r '.statusLine.command // empty' "$SETTINGS"
}

guard_wrapped() {
  case "$(current_cmd)" in *claude-usage-guard/statusline-tee.sh*) return 0 ;; esac
  return 1
}

write_settings() {
  # Arguments go to jq; the result replaces settings.json atomically after a backup.
  local tmp
  [ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
  jq -e . "$SETTINGS" >/dev/null || { echo "error: $SETTINGS is not valid JSON, not touching it" >&2; exit 1; }
  cp "$SETTINGS" "$STATE_DIR/settings.json.bak.$(date +%Y%m%d%H%M%S)"
  tmp=$(mktemp "$SETTINGS.XXXXXX")
  jq "$@" "$SETTINGS" > "$tmp"
  mv "$tmp" "$SETTINGS"
}

copy_script() {
  mkdir -p "$STATE_DIR"
  cp "$SRC" "$TARGET"
  chmod +x "$TARGET"
}

installed_where() {
  if guard_wrapped && [ "$(guard_inner_cmd)" = "$CMD" ]; then
    echo "inside the usage-guard wrapper"
  elif [ "$(current_cmd)" = "$CMD" ]; then
    echo "as statusLine.command"
  fi
}

case "${1:-status}" in
  install)
    copy_script
    where=$(installed_where)
    if [ -n "$where" ]; then
      echo "already installed ($where); script refreshed"
      exit 0
    fi
    if guard_wrapped; then
      guard_inner_cmd > "$PREVIOUS"
      printf '%s' "$CMD" > "$GUARD_INNER"
      echo "installed inside the usage-guard wrapper (statusLine.command unchanged)"
    else
      current_cmd > "$PREVIOUS"
      write_settings --arg cmd "$CMD" \
        '.statusLine = ((.statusLine // {}) + {type: "command", command: $cmd})'
      echo "installed as statusLine.command: $CMD"
    fi
    prev=$(cat "$PREVIOUS")
    echo "previous statusline: ${prev:-(none)}"
    ;;

  uninstall)
    where=$(installed_where)
    if [ -z "$where" ]; then
      echo "not installed (statusLine.command is: $(current_cmd)); nothing changed"
      exit 0
    fi
    prev=$(cat "$PREVIOUS" 2>/dev/null || true)
    if [ "$where" = "inside the usage-guard wrapper" ]; then
      printf '%s' "$prev" > "$GUARD_INNER"
      echo "uninstalled; usage-guard inner statusline restored to: ${prev:-(none)}"
    else
      if [ -n "$prev" ]; then
        write_settings --arg cmd "$prev" '.statusLine.command = $cmd'
      else
        write_settings 'del(.statusLine)'
      fi
      echo "uninstalled; statusLine.command restored to: ${prev:-(removed)}"
    fi
    rm -f "$TARGET" "$PREVIOUS"
    ;;

  refresh)
    if [ -f "$TARGET" ] && ! cmp -s "$SRC" "$TARGET"; then
      copy_script
    fi
    ;;

  status)
    where=$(installed_where)
    if [ -n "$where" ]; then
      echo "installed ($where)"
      cmp -s "$SRC" "$TARGET" && echo "script: up to date" || echo "script: differs from plugin copy (run install to refresh)"
      echo "previous statusline: $(cat "$PREVIOUS" 2>/dev/null || echo '(unknown)')"
    else
      echo "not installed (statusLine.command is: $(current_cmd))"
    fi
    ;;

  *)
    echo "usage: $0 install|uninstall|status|refresh" >&2
    exit 2
    ;;
esac
