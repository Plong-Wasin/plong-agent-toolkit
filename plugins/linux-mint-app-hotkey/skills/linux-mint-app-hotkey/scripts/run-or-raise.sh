#!/usr/bin/env bash
# Run-or-raise template: focus an existing window of an app, or launch it if none is open.
# Copy this to ~/.local/bin/<app-slug>-toggle.sh, fill in the two variables below, chmod +x it,
# then point a Cinnamon custom keybinding's command at the copy.
set -euo pipefail

WM_CLASS_PATTERN="CHANGE_ME"   # case-insensitive substring matched against `wmctrl -lx` column 3 (instance.class)
LAUNCH_CMD=(CHANGE_ME)         # command + args that start the app, e.g. (wezterm start --cwd .)

win_id=$(wmctrl -lx | grep -i -- "$WM_CLASS_PATTERN" | head -n1 | awk '{print $1}') || true

if [ -n "${win_id:-}" ]; then
    wmctrl -ia "$win_id"
else
    setsid "${LAUNCH_CMD[@]}" >/dev/null 2>&1 &
fi
