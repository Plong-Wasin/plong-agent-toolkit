#!/bin/bash
# Statusline wrapper installed by the usage-guard-statusline skill.
#
# Claude Code hands the statusline the plan usage it read off the response
# headers of its own model calls (.rate_limits). This saves that part to one
# snapshot per session for usage-guard.sh, which then needs no extra request,
# and passes the input on to the statusline command that was there before.
input=$(cat)

# Per-profile directory, matching usage-guard.sh.
PROFILE_KEY=$(printf '%s' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" | cksum | cut -d' ' -f1)
SNAP_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/claude-usage-guard/$PROFILE_KEY/statusline"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/claude-usage-guard"
mkdir -p "$SNAP_DIR"

sid=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)
if [[ "$sid" =~ ^[A-Za-z0-9_-]+$ ]] \
  && printf '%s' "$input" | jq -e '.rate_limits | type == "object"' >/dev/null 2>&1; then
  tmp=$(mktemp "$SNAP_DIR/.snap.XXXXXX")
  if printf '%s' "$input" | jq -c '{session_id, transcript_path, rate_limits}' > "$tmp" 2>/dev/null; then
    mv "$tmp" "$SNAP_DIR/$sid.json"
  else
    rm -f "$tmp"
  fi
fi

# Snapshots of sessions untouched for a day are of no further use.
find "$SNAP_DIR" -maxdepth 1 -name '*.json' -mmin +1440 -delete 2>/dev/null

# Per-profile inner statusline; the unsuffixed file is the pre-profile fallback.
inner=$(cat "$STATE_DIR/inner-statusline.$PROFILE_KEY" 2>/dev/null || cat "$STATE_DIR/inner-statusline" 2>/dev/null)
[ -n "$inner" ] && printf '%s' "$input" | bash -c "$inner"
exit 0
