---
name: usage-guard-statusline
description: "One-time setup: wrap the Claude Code statusline so the usage-guard hook can read plan usage (5-hour / weekly %) from it. Most checks then need no API call, and they keep working while the usage endpoint is rate limited. Arguments: install (default), status, uninstall."
argument-hint: "[install|status|uninstall]"
disable-model-invocation: true
---

# Usage-guard statusline source

The user ran this command to change their own Claude Code configuration, so carry out the requested action instead of only describing it.

The `usage-guard-hook` plugin reads plan usage from the `/api/oauth/usage` endpoint. This setup adds a second source. Claude Code passes the statusline the usage it read off its own model responses (`.rate_limits`). A wrapper saves that to `~/.cache/claude-usage-guard/statusline/<session>.json`, then runs the statusline the user already had, so the visible statusline does not change.

For each limit the hook uses whichever reading is newer. It calls the endpoint only when the statusline has no live reading for the 5-hour or the weekly limit. A snapshot counts only while its session is active, so the endpoint still covers `claude -p`, fresh sessions, and stretches where only subagents run. The hook works without this setup; the setup only adds the second source.

## Run

The action is `$ARGUMENTS`; when that is empty, use `install`. Run the script in this skill's base directory:

```bash
bash <this skill's base directory>/scripts/setup.sh <install|status|uninstall>
```

- `install` wraps the current `statusLine.command` in `~/.claude/settings.json`. It saves the old command to `~/.local/share/claude-usage-guard/inner-statusline` and backs up settings.json to that folder first. Re-running it is safe: it only refreshes the wrapper.
- `status` shows whether the wrapper is installed and lists each session snapshot with its age.
- `uninstall` restores the original statusline command and deletes the wrapper and snapshots.

Let the script make the change rather than editing settings.json by hand. It validates the JSON and keeps a backup. It refuses to touch an invalid settings.json; if that happens, report it and stop.

## After install

The plugin's SessionStart hook keeps the installed wrapper in sync with plugin updates, so this command never needs to run again.

To verify, wait for the next statusline refresh, which happens after the next model response, then run `status`. It should list a snapshot for the current session written a few seconds ago. If no snapshot appears, the account may not receive `rate_limits` (for example, with API-key billing). The hook then keeps using the endpoint alone, so nothing breaks.

Report the outcome to the user in their language:
- what changed;
- the inner statusline command that was kept;
- how to undo it (`uninstall`).
