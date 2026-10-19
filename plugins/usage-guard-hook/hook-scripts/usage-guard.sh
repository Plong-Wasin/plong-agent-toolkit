#!/bin/bash
# Stop Claude Code before a claude.ai plan limit (5-hour session / weekly) runs out,
# so the work never spills over into paid extra-usage credits.
#
# Reads the plan usage from two sources and, per limit, uses the newer reading:
#   - statusline snapshots, when the usage-guard-statusline skill has wrapped
#     the statusline (optional, free, refreshed after every model response);
#   - https://api.anthropic.com/api/oauth/usage with the OAuth token in
#     ~/.claude/.credentials.json, cached briefly. Called only when the
#     statusline has no live reading, so without the skill it is the only source.
# When a limit is at or above its threshold:
#   - UserPromptSubmit: blocks the prompt before it reaches the model.
#   - PreToolUse:       denies the tool call and ends the turn (continue:false).
#
# The usage endpoint is itself rate limited. Every session shares one cache and
# one lock, so it is called at most once per TTL however many sessions run. On
# HTTP 429 the Retry-After header (or an exponential backoff) is honoured, and
# on other failures the next attempt waits too, so a broken network never adds
# a curl timeout to every tool call.
#
# Tunables (environment variables, e.g. via "env" in ~/.claude/settings.json):
#   CLAUDE_USAGE_GUARD_SESSION_THRESHOLD  block 5-hour limit at this %  (default 93, decimals ok)
#   CLAUDE_USAGE_GUARD_WEEKLY_THRESHOLD   block weekly limits at this % (default 95, decimals ok)
#   CLAUDE_USAGE_GUARD_WARN               0 = no threshold warnings at all (default 1)
#   CLAUDE_USAGE_GUARD_SESSION_WARN       warn 5-hour limit at this %, or "off" (default 80)
#   CLAUDE_USAGE_GUARD_WEEKLY_WARN        warn weekly limits at this %, or "off" (default 85)
#   CLAUDE_USAGE_GUARD_TTL                seconds to reuse cached usage (default 180)
#   CLAUDE_USAGE_GUARD_STATUSLINE_FRESH   max age of a statusline snapshot, seconds (default 120)
#   CLAUDE_USAGE_GUARD_MAX_STALE          oldest usable cache, seconds  (default 600)
#   CLAUDE_USAGE_GUARD_FAIL_CLOSED        1 = block when usage is unknown (default 0)
#   CLAUDE_USAGE_GUARD_DISABLE            1 = skip every check
INPUT=$(cat)
EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')

[ "${CLAUDE_USAGE_GUARD_DISABLE:-0}" = "1" ] && { echo '{}'; exit 0; }

# Percentages may be decimals (92.5). A threshold that is not a number falls back
# to its default, so a typo never blocks (or never warns) by accident.
num_or() { [[ "$1" =~ ^[0-9]+(\.[0-9]+)?$ ]] && echo "$1" || echo "$2"; }
SESSION_THRESHOLD=$(num_or "${CLAUDE_USAGE_GUARD_SESSION_THRESHOLD:-}" 93)
WEEKLY_THRESHOLD=$(num_or "${CLAUDE_USAGE_GUARD_WEEKLY_THRESHOLD:-}" 95)
SESSION_WARN="${CLAUDE_USAGE_GUARD_SESSION_WARN:-80}"
WEEKLY_WARN="${CLAUDE_USAGE_GUARD_WEEKLY_WARN:-85}"
WARN_ENABLED="${CLAUDE_USAGE_GUARD_WARN:-1}"
TTL="${CLAUDE_USAGE_GUARD_TTL:-180}"
STATUSLINE_FRESH="${CLAUDE_USAGE_GUARD_STATUSLINE_FRESH:-120}"
MAX_STALE="${CLAUDE_USAGE_GUARD_MAX_STALE:-600}"
FAIL_CLOSED="${CLAUDE_USAGE_GUARD_FAIL_CLOSED:-0}"

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/claude-usage-guard"
CACHE="$CACHE_DIR/usage.json"
SNAP_DIR="$CACHE_DIR/statusline"  # one snapshot per session, written by statusline-tee.sh
BACKOFF="$CACHE_DIR/backoff"   # "<retry-at epoch> <consecutive failures> <reason>"
CREDS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.credentials.json"
mkdir -p "$CACHE_DIR"

now() { date +%s; }

cache_age() {
  [ -s "$CACHE" ] || { echo 999999; return; }
  echo $(( $(now) - $(stat -c %Y "$CACHE") ))
}

backoff_field() {
  [ -s "$BACKOFF" ] || { echo "${2:-0}"; return; }
  awk -v n="$1" '{print $n}' "$BACKOFF"
}

set_backoff() {
  local wait="$1" reason="$2" fails
  fails=$(( $(backoff_field 2 0) + 1 ))
  echo "$(( $(now) + wait )) $fails $reason" > "$BACKOFF"
}

fetch_usage() {
  local token tmp hdr code retry fails wait
  token=$(jq -er '.claudeAiOauth.accessToken' "$CREDS" 2>/dev/null) || { set_backoff 300 no-token; return 1; }
  tmp=$(mktemp "$CACHE_DIR/usage.XXXXXX")
  hdr=$(mktemp "$CACHE_DIR/headers.XXXXXX")
  # Header goes through curl's stdin config so the token never shows up in ps.
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$token" \
    | curl -sS --max-time 8 -K - \
        -H "anthropic-beta: oauth-2025-04-20" \
        -D "$hdr" -o "$tmp" -w '%{http_code}' \
        https://api.anthropic.com/api/oauth/usage 2>/dev/null)
  fails=$(backoff_field 2 0)

  if [ "$code" = "200" ] && jq -e 'type == "object"' "$tmp" >/dev/null 2>&1; then
    mv "$tmp" "$CACHE"
    rm -f "$hdr" "$BACKOFF"
    return 0
  fi

  if [ "$code" = "429" ]; then
    retry=$(awk 'tolower($1) == "retry-after:" {gsub(/\r/, "", $2); print $2}' "$hdr")
    if [[ "$retry" =~ ^[0-9]+$ ]]; then
      wait="$retry"
    else
      # 60s, 120s, 240s ... capped at 15 minutes.
      wait=$(( 60 << (fails < 4 ? fails : 4) ))
      [ "$wait" -gt 900 ] && wait=900
    fi
    set_backoff "$wait" rate-limited
  elif [ "$code" = "401" ] || [ "$code" = "403" ]; then
    # Expired token: Claude Code refreshes it on its next API call.
    set_backoff 60 "auth-$code"
  else
    # Network error or 5xx: 15s, 30s, 60s ... capped at 5 minutes.
    wait=$(( 15 << (fails < 5 ? fails : 5) ))
    [ "$wait" -gt 300 ] && wait=300
    set_backoff "$wait" "http-${code:-000}"
  fi
  rm -f "$tmp" "$hdr"
  return 1
}

mtime() { stat -c %Y "$1" 2>/dev/null || echo 0; }

# Plan limits from the statusline snapshots (see plugins/usage-guard-hook/skills/usage-guard-statusline).
# Claude Code reads them off the response headers of its own model calls, so this
# costs no request. A snapshot counts only while its session is working: both the
# snapshot and the session transcript changed within STATUSLINE_FRESH seconds.
# An idle session still re-renders its statusline with old numbers, and those must
# not pass for current. Each limit carries "at", the time its numbers are from: the
# older of the snapshot and the transcript, since the numbers come from the last
# model response and the snapshot can only be as new as its last render.
statusline_limits() {
  local f tp t at
  t=$(now)
  for f in "$SNAP_DIR"/*.json; do
    [ -f "$f" ] || continue
    [ $(( t - $(mtime "$f") )) -le "$STATUSLINE_FRESH" ] || continue
    tp=$(jq -r '.transcript_path // empty' "$f" 2>/dev/null)
    [ -n "$tp" ] && [ $(( t - $(mtime "$tp") )) -le "$STATUSLINE_FRESH" ] || continue
    at=$(mtime "$f"); [ "$(mtime "$tp")" -lt "$at" ] && at=$(mtime "$tp")
    # A limit whose reset time has passed is from the previous window: skip it.
    jq -c --argjson now "$t" --argjson at "$at" '
      .rate_limits // {} | to_entries[]
      | select(.key == "five_hour" or .key == "seven_day")
      | select((.value.used_percentage | type) == "number")
      | select((.value.resets_at // ($now + 1)) > $now)
      | {name: .key,
         kind: (if .key == "five_hour" then "session" else "weekly" end),
         pct: .value.used_percentage,
         resets: (.value.resets_at | if . then todate else null end),
         at: $at, source: "statusline"}
    ' "$f" 2>/dev/null
  done | jq -sc 'if length == 0 then empty else . end'
}

block() {
  local msg="$1"
  case "$EVENT" in
    UserPromptSubmit)
      jq -n --arg m "$msg" '{decision: "block", reason: $m}' ;;
    PreToolUse)
      jq -n --arg m "$msg" '{
        continue: false,
        stopReason: $m,
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: $m
        }
      }' ;;
    *)
      jq -n --arg m "$msg" '{continue: false, stopReason: $m}' ;;
  esac
  exit 0
}

# Two sources, and for each limit the newer reading wins:
#   - statusline snapshots: free and refreshed after every model response, but
#     only while an interactive session is working (not claude -p, not while
#     only subagents run);
#   - the usage endpoint: works everywhere, but costs a request and can be rate
#     limited. It is called only when the statusline has no live reading for the
#     5-hour or the weekly limit.
SL_LIMITS=$(statusline_limits)
SL_KINDS=$(jq -r '[.[].kind] | unique | length' <<< "${SL_LIMITS:-[]}")

if [ "$SL_KINDS" -lt 2 ] && [ "$(cache_age)" -ge "$TTL" ] && [ "$(now)" -ge "$(backoff_field 1 0)" ]; then
  # Parallel hooks share one fetch.
  exec 9>"$CACHE_DIR/lock"
  if flock -w 10 9 && [ "$(cache_age)" -ge "$TTL" ] && [ "$(now)" -ge "$(backoff_field 1 0)" ]; then
    fetch_usage
  fi
  exec 9>&-
fi

# Every plan limit tagged session (5-hour) or weekly, named like the statusline
# ones so the two can be compared. A locked limit counts as 100%.
API_LIMITS=""
if [ "$(cache_age)" -le "$MAX_STALE" ]; then
  API_LIMITS=$(jq -c --argjson at "$(mtime "$CACHE")" '
    def kind(n): if (n | test("session|five_hour")) then "session" else "weekly" end;
    def norm(n): {"session": "five_hour", "weekly_all": "seven_day"}[n] // n;
    [ (.limits // [])[] | select(.percent != null)
        | {name: norm(.kind), kind: kind(.group // .kind), pct: .percent, resets: .resets_at} ]
    + [ to_entries[]
        | select((.value | type) == "object" and (.value.utilization | type) == "number")
        | {name: .key, kind: kind(.key),
           pct: (if .value.locked_reason != null then 100 else .value.utilization end),
           resets: .value.resets_at} ]
    | group_by(.name) | map(max_by(.pct) + {at: $at, source: "api"})
  ' "$CACHE")
fi

if [ -z "$SL_LIMITS" ] && [ -z "$API_LIMITS" ]; then
  reason=$(backoff_field 3 unknown)
  if [ "$FAIL_CLOSED" = "1" ]; then
    block "usage-guard: could not read plan usage (${reason}), blocking because CLAUDE_USAGE_GUARD_FAIL_CLOSED=1."
  fi
  jq -n --arg m "usage-guard: could not read plan usage (${reason}); continuing unchecked." '{systemMessage: $m}'
  exit 0
fi

# Per limit, keep the newest reading (the higher one on a tie). Limits only the
# endpoint reports, such as seven_day_opus, come from its cache.
LIMITS=$(jq -sc 'add | group_by(.name) | map(sort_by(.at, .pct) | last)' \
  <<< "${SL_LIMITS:-[]} ${API_LIMITS:-[]}")

# Highest limit of a kind as "<pct> <name> <resets_at>".
worst() {
  echo "$LIMITS" | jq -r --arg k "$1" '
    [ .[] | select(.kind == $k) ] | max_by(.pct)
    // {pct: 0, name: "none", resets: ""}
    | "\(.pct) \(.name) \(.resets // "")"'
}

fmt_time() { [ -n "$1" ] && date -d "$1" '+%Y-%m-%d %H:%M' 2>/dev/null; }

read -r S_PCT S_NAME S_RESETS <<< "$(worst session)"
read -r W_PCT W_NAME W_RESETS <<< "$(worst weekly)"
S_AT=$(fmt_time "$S_RESETS"); W_AT=$(fmt_time "$W_RESETS")

# True when the first number is at or above the second (decimals allowed).
ge() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a + 0 >= b + 0) }'; }
# 92.50 -> 92.5, 44 -> 44
pct() { awk -v a="$1" 'BEGIN { printf "%.1f", a }' | sed 's/\.0$//'; }

if ge "$S_PCT" "$SESSION_THRESHOLD"; then
  block "usage-guard: 5-hour limit (${S_NAME}) at $(pct "$S_PCT")% (threshold ${SESSION_THRESHOLD}%). Stopped so extra-usage credits are not spent. Resets ${S_AT:-later}. Set CLAUDE_USAGE_GUARD_DISABLE=1 to override."
fi
if ge "$W_PCT" "$WEEKLY_THRESHOLD"; then
  block "usage-guard: weekly limit (${W_NAME}) at $(pct "$W_PCT")% (threshold ${WEEKLY_THRESHOLD}%). Stopped so extra-usage credits are not spent. Resets ${W_AT:-later}. Set CLAUDE_USAGE_GUARD_DISABLE=1 to override."
fi

# True when warnings are on and the level is a number the percent has reached.
should_warn() {
  [ "$WARN_ENABLED" != "0" ] && [[ "$2" =~ ^[0-9]+(\.[0-9]+)?$ ]] && ge "$1" "$2"
}

if [ "$EVENT" = "UserPromptSubmit" ]; then
  WARNINGS=()
  should_warn "$S_PCT" "$SESSION_WARN" && WARNINGS+=("5-hour $(pct "$S_PCT")% (blocks at ${SESSION_THRESHOLD}%, resets ${S_AT:-later})")
  should_warn "$W_PCT" "$WEEKLY_WARN" && WARNINGS+=("weekly $(pct "$W_PCT")% (blocks at ${WEEKLY_THRESHOLD}%, resets ${W_AT:-later})")
  if [ "${#WARNINGS[@]}" -gt 0 ]; then
    SPENT=$(jq -r '
      (.spend.used // {amount_minor: 0, exponent: 2, currency: "USD"})
      | "\(.amount_minor / pow(10; .exponent) * 100 | round / 100) \(.currency)"
    ' "$CACHE")
    JOINED=$(printf '%s; ' "${WARNINGS[@]}")
    MSG="usage-guard: ${JOINED%; }. Extra usage spent this month: ${SPENT}."
    jq -n --arg m "$MSG" '{systemMessage: $m}'
    exit 0
  fi
fi

echo '{}'
