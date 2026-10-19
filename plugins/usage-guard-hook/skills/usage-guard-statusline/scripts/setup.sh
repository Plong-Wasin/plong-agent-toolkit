#!/bin/bash
# Wrap (or unwrap) the user's Claude Code statusline so usage-guard.sh can read
# plan usage from it.
#
#   setup.sh install    wrap the current statusline (safe to re-run)
#   setup.sh uninstall  restore the statusline that was there before
#   setup.sh status     show what is installed and how fresh the snapshots are
#   setup.sh refresh    re-copy the wrapper if installed (run by the SessionStart
#                       hook so plugin updates reach the installed copy); silent
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$SKILL_DIR/scripts/statusline-tee.sh"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/claude-usage-guard"
WRAPPER="$STATE_DIR/statusline-tee.sh"
INNER="$STATE_DIR/inner-statusline"
SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
SNAP_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/claude-usage-guard/statusline"
WRAP_CMD="bash $WRAPPER"

current_cmd() {
  [ -f "$SETTINGS" ] || { echo ""; return; }
  jq -r '.statusLine.command // empty' "$SETTINGS"
}

write_settings() {
  # $1: jq filter applied to settings.json, written atomically after a backup.
  local tmp
  [ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
  jq -e . "$SETTINGS" >/dev/null || { echo "error: $SETTINGS is not valid JSON, not touching it" >&2; exit 1; }
  cp "$SETTINGS" "$STATE_DIR/settings.json.bak.$(date +%Y%m%d%H%M%S)"
  tmp=$(mktemp "$SETTINGS.XXXXXX")
  jq "$@" "$SETTINGS" > "$tmp"
  mv "$tmp" "$SETTINGS"
}

copy_wrapper() {
  mkdir -p "$STATE_DIR"
  cp "$SRC" "$WRAPPER"
  chmod +x "$WRAPPER"
}

case "${1:-status}" in
  install)
    copy_wrapper
    cur=$(current_cmd)
    if [ "$cur" = "$WRAP_CMD" ]; then
      echo "already installed; wrapper refreshed"
      echo "inner statusline: $(cat "$INNER" 2>/dev/null || echo '(none)')"
      exit 0
    fi
    printf '%s' "$cur" > "$INNER"
    write_settings --arg cmd "$WRAP_CMD" \
      '.statusLine = ((.statusLine // {}) + {type: "command", command: $cmd})'
    echo "installed"
    echo "statusLine.command: $WRAP_CMD"
    echo "inner statusline:   ${cur:-(none: the statusline will stay empty)}"
    ;;

  uninstall)
    cur=$(current_cmd)
    if [ "$cur" != "$WRAP_CMD" ]; then
      echo "not installed (statusLine.command is: ${cur:-(none)}); nothing changed"
      exit 0
    fi
    inner=$(cat "$INNER" 2>/dev/null || true)
    if [ -n "$inner" ]; then
      write_settings --arg cmd "$inner" '.statusLine.command = $cmd'
    else
      write_settings 'del(.statusLine)'
    fi
    rm -f "$WRAPPER" "$INNER"
    rm -rf "$SNAP_DIR"
    echo "uninstalled; statusLine.command restored to: ${inner:-(removed)}"
    ;;

  refresh)
    if [ "$(current_cmd 2>/dev/null || true)" = "$WRAP_CMD" ] && ! cmp -s "$SRC" "$WRAPPER"; then
      copy_wrapper
    fi
    ;;

  status)
    cur=$(current_cmd)
    if [ "$cur" = "$WRAP_CMD" ]; then
      echo "installed"
      echo "inner statusline: $(cat "$INNER" 2>/dev/null || echo '(none)')"
    else
      echo "not installed (statusLine.command is: ${cur:-(none)})"
    fi
    now=$(date +%s)
    shopt -s nullglob
    snaps=("$SNAP_DIR"/*.json)
    echo "snapshots: ${#snaps[@]}"
    for f in "${snaps[@]}"; do
      jq -r --arg age "$(( now - $(stat -c %Y "$f") ))" '
        "  \(.session_id): 5h=\(.rate_limits.five_hour.used_percentage // "-")% "
        + "weekly=\(.rate_limits.seven_day.used_percentage // "-")% (written \($age)s ago)"
      ' "$f"
    done
    ;;

  *)
    echo "usage: $0 install|uninstall|status|refresh" >&2
    exit 2
    ;;
esac
