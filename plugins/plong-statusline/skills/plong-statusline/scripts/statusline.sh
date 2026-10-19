#!/usr/bin/env bash
# Status line: model + reasoning effort, cwd, git branch, context window
# usage, and Claude.ai rate limits (5h / weekly), when available.

input=$(cat)

# Single jq call, every field defaulted to "" via `// ""` so missing/null
# values never render as the literal string "null" and never abort the
# pipeline. Fields are joined with \x1f (unit separator) and split back out
# with `read` -- NOT a tab: bash's `read` treats tab as "IFS whitespace" and
# collapses consecutive delimiters, silently swallowing empty fields and
# shifting every value after the first gap. \x1f is not whitespace, so empty
# fields are preserved correctly.
IFS=$'\x1f' read -r cwd model ctx_used five_used five_reset seven_used seven_reset effort_level <<< "$(printf '%s' "$input" | jq -r '
  [
    (.workspace.current_dir // ""),
    (.model.display_name // ""),
    (.context_window.used_percentage // ""),
    (.rate_limits.five_hour.used_percentage // ""),
    (.rate_limits.five_hour.resets_at // ""),
    (.rate_limits.seven_day.used_percentage // ""),
    (.rate_limits.seven_day.resets_at // ""),
    (.effort.level // "")
  ] | join("\u001f")
' 2>/dev/null)"

# Shorten cwd for display: show only the last path component (basename);
# $HOME itself shows as ~ and / as /.
dir_display="$cwd"
if [ -n "$cwd" ]; then
    if [ -n "$HOME" ] && [ "$cwd" = "$HOME" ]; then
        dir_display="~"
    elif [ "$cwd" = "/" ]; then
        dir_display="/"
    else
        dir_display="${cwd%/}"
        dir_display="${dir_display##*/}"
    fi
fi

branch=""
if [ -n "$cwd" ]; then
    branch=$(git --no-optional-locks -C "$cwd" branch --show-current 2>/dev/null)
fi

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
RED='\033[0;31m'
BOLD_RED='\033[1;31m'
DIM='\033[2m'
RESET='\033[0m'

# Usage percentage at/above this is considered "at limit" -> red + warning mark.
WARN_THRESHOLD=90

# 1. model + effort
if [ -n "$model" ]; then
    printf "${GREEN}%s${RESET}" "$model"
    if [ -n "$effort_level" ]; then
        printf " ${DIM}\xc2\xb7${RESET} ${CYAN}%s${RESET}" "$effort_level"
    fi
fi

# 2. current directory
if [ -n "$dir_display" ]; then
    printf " ${DIM}in${RESET} ${BLUE}%s${RESET}" "$dir_display"
fi

# 3. git branch
if [ -n "$branch" ]; then
    printf " ${DIM}(${YELLOW}%s${DIM})${RESET}" "$branch"
fi

# Picks a color + optional "over limit" warning marker for a usage percentage.
# Sets globals: PCT_COLOR, PCT_WARN (empty, or a leading "\xe2\x9a\xa0 " marker).
pct_style() {
    local pct="$1" normal_color="$2"
    if [ "$pct" -ge "$WARN_THRESHOLD" ] 2>/dev/null; then
        PCT_COLOR="$BOLD_RED"
        PCT_WARN="\xe2\x9a\xa0 "
    else
        PCT_COLOR="$normal_color"
        PCT_WARN=""
    fi
}

# 4. context window usage
if [ -n "$ctx_used" ]; then
    ctx_fmt=$(printf '%.0f' "$ctx_used" 2>/dev/null)
    if [ -n "$ctx_fmt" ]; then
        pct_style "$ctx_fmt" "$MAGENTA"
        printf " ${DIM}ctx:${RESET}${PCT_WARN}${PCT_COLOR}%s%%${RESET}" "$ctx_fmt"
    fi
fi

# 5. five-hour rate limit
if [ -n "$five_used" ]; then
    five_fmt=$(printf '%.0f' "$five_used" 2>/dev/null)
    if [ -n "$five_fmt" ]; then
        pct_style "$five_fmt" "$YELLOW"
        printf " ${DIM}5h:${RESET}${PCT_WARN}${PCT_COLOR}%s%%${RESET}" "$five_fmt"
        if [ -n "$five_reset" ]; then
            five_time=$(date -d "@$five_reset" +%H:%M 2>/dev/null)
            if [ -n "$five_time" ]; then
                printf "${DIM}\xe2\x86\x92${RESET}%s" "$five_time"
            fi
        fi
    fi
fi

# 6. weekly rate limit
if [ -n "$seven_used" ]; then
    seven_fmt=$(printf '%.0f' "$seven_used" 2>/dev/null)
    if [ -n "$seven_fmt" ]; then
        pct_style "$seven_fmt" "$YELLOW"
        printf " ${DIM}wk:${RESET}${PCT_WARN}${PCT_COLOR}%s%%${RESET}" "$seven_fmt"
        if [ -n "$seven_reset" ]; then
            seven_time=$(date -d "@$seven_reset" +"%a %H:%M" 2>/dev/null)
            if [ -n "$seven_time" ]; then
                printf "${DIM}\xe2\x86\x92${RESET}%s" "$seven_time"
            fi
        fi
    fi
fi

printf "\n"
