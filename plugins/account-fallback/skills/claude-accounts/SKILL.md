---
name: claude-accounts
description: Manage Claude subscription fallback accounts, log in or import existing logins, set account priority, and configure separate 5-hour and weekly usage thresholds. Use for configuring the account-fallback plugin.
---

# Claude subscription accounts

Use this skill's `scripts/accounts.py` to carry out `$ARGUMENTS` or the user's account configuration request. Resolve the script relative to this skill's directory, including when installed in a plugin cache. Start with `status` to see saved account names, effective thresholds, and the current configuration directory. With no requested change, show status.

Run commands as `python3 "<skill directory>/scripts/accounts.py" ...`. Account names use lowercase letters, digits, underscores, and hyphens. Lower priority numbers are preferred; equal numbers sort by name. The hook always selects the first enabled, eligible account, so a preferred account returns automatically at the next hook check after its usage reset is verified.

## Account setup

- `import main --priority 1`: save the subscription login in the current `CLAUDE_CONFIG_DIR`, or `~/.claude` when unset. Use `--from-config-dir "/absolute/profile/path"` to import another existing profile, including an Orca profile. Import copies the OAuth credential; it doesn't move the source profile.
- `login backup --priority 2 [--email user@example.com]`: run the real `claude auth login --claudeai` in an isolated temporary config directory, then save the resulting login. The human completes browser authentication. Run in an interactive terminal when the available shell tool cannot keep the login process open; show the exact command and do not claim login completed before it exits successfully. Login does not run an inference request.
- `priority backup 3` changes one rank. `order main backup third` assigns consecutive ranks and requires every saved name exactly once.
- `account backup disable` / `account backup enable` excludes or includes a saved account without deleting its login.

The manager verifies account and organization identity before saving credentials. Re-login under an existing name refreshes that same identity and updates bound copies; a different identity needs a new name. Let the manager handle credentials. Show its status output rather than reading or printing credential files, access tokens, refresh tokens, or raw HTTP responses.

If browser login succeeds but verification/storage is temporarily unavailable, the manager preserves the isolated login folder and prints an `import ... --from-config-dir ...` recovery command. Retry that command to save the login without opening another browser flow. After a successful recovery import, that retained login folder can be removed. Imports copy a grant: an unmanaged original profile can still refresh its own copy. Enable fallback on live profiles that share that grant so the manager can synchronize them, or use a separate `login` for a managed backup.

## Thresholds and activation

```bash
python3 "<skill directory>/scripts/accounts.py" configure --five-hour 90 --weekly 95
python3 "<skill directory>/scripts/accounts.py" configure --account backup --five-hour 85 --weekly 92
python3 "<skill directory>/scripts/accounts.py" configure --cache-ttl 180 --statusline-fresh 60 --api-max-age 600
python3 "<skill directory>/scripts/accounts.py" enable
python3 "<skill directory>/scripts/accounts.py" check
```

Defaults are 93% for 5 hours and 95% weekly. An account is ineligible when **either** percentage is at or above its threshold, including model-specific weekly limits. Account overrides inherit unspecified global thresholds. Percentages may be decimals (e.g. `--five-hour 92.5`) and must be greater than zero and at most 100. Usage readings keep their decimals, compared with `>=`. `--cache-ttl` is the minimum gap between usage API calls for one account (default 60 seconds, 1–3600), with separate caches/backoff for each account. Unknown or stale usage does not qualify an account.

### Statusline usage source (optional)

```bash
python3 "<skill directory>/scripts/accounts.py" statusline install
python3 "<skill directory>/scripts/accounts.py" statusline uninstall
```

`install` wraps the profile's `statusLine` in `settings.json`: the wrapper saves each session's `rate_limits` (read by Claude Code from its own model responses, so free) and then renders the previous statusline unchanged. It runs a copy of this script in the private state directory, refreshed at `SessionStart`, so plugin updates do not break the command. `uninstall` restores the previous `statusLine`. Both accept the global `--config-dir`. Run `enable` first.

A snapshot counts for the active account only when its session started after the profile last switched accounts and after installation. A running session keeps its original credential, so its numbers could belong to the previous account. A reading is as old as the older of the snapshot and the transcript.

The hook uses whichever reading is newer, the statusline or the cached API result, for the 5-hour and weekly limits. Model-specific weekly limits always come from the API reading. It calls the API only when no statusline reading is newer than `--statusline-fresh` (default 60 seconds) and the cached API reading is at least `--cache-ttl` old, has a window that has since reset, or, next to a fresh statusline, is older than `--api-max-age` (default 600 seconds). Standby accounts and `check` use the API as before. All three intervals are global. Profiles enabled before this feature have no switch time recorded; re-run `enable` to let the statusline count.

`enable` activates automatic fallback only for the current config directory, after the current login has been imported. Target another profile with the global option **before** the command:

```bash
python3 "<skill directory>/scripts/accounts.py" --config-dir "/absolute/orca/profile/home" enable
```

`disable` stops automatic switching and background credential updates for that directory, leaving the currently selected credential in place. To undo a fallback and return to the preferred eligible account, use `check` before disabling. `check` evaluates eligibility and can actually switch accounts; `status` is read-only and makes no network requests.

Before activation, check whether `usage-guard-hook` is also enabled in that Claude profile. Both plugins enforce usage independently; the old guard can block before fallback runs and uses a cache shared across accounts. Explain this conflict and disable the old guard for that profile as part of replacing it with fallback when the user requested that replacement. Preserve unrelated hooks and statusline settings.

## Runtime behavior and recovery

The packaged hook checks before prompts and tools, after tool calls, and at normal turn completion. `StopFailure` with `rate_limit` cools down the failed account for five minutes and prepares an eligible alternative. It cannot replay the failed turn; tell the user to retry it. A reset is verified on the next hook/check, not by an idle background timer.

While a preferred account waits for its reset, it is not polled. Usage only grows within a window, so its newest reading at a threshold (API, or the statusline reading saved while it was active) proves it ineligible until that limit's reset time. The first check after the reset calls the usage API once and switches back if the account is eligible. The block message names that reset time.

A switch also rewrites the profile's cached identity, `oauthAccount` in its global config (`<config dir>/.claude.json`, or `~/.claude.json` for the default `~/.claude`). Claude Code reads the account and organization from there, not from the credential, so swapping only `.credentials.json` leaves `claude auth status` and the session on the old identity. The manager archives each account's `oauthAccount` on import, enable and switch, only when its account and organization UUIDs match the verified identity. Without an archived copy it removes the stale field so Claude Code fetches the new one. Other keys in that file are preserved.

Enabled profiles sharing an account adopt its latest captured refresh grant; older profile copies never replace a newer archived grant. Disabled profiles are excluded. Backoff applies even when a previously low usage percentage is cached. Do not describe unknown eligibility as spare capacity.

If all accounts reach a threshold or usage cannot be verified, prompts/tools are blocked. Use the manager directly in a terminal to fix configuration when the model cannot respond. Login/management commands invoked directly through this installed script can pass the tool guard for recovery.

This release targets **Linux/WSL subscription file authentication**. It rejects known environment auth overrides and `apiKeyHelper`. Automatic adoption by a running Claude process, especially Orca Chat, remains experimental: the implementation has fixture tests, not a live two-account acceptance test. Requests already streaming retain their original authentication. Several sessions sharing a config directory share account changes. Native OAuth lock paths and the profile/usage/refresh endpoints follow Claude Code 2.1.300 internals and may change with upgrades.

Private state defaults to `${XDG_DATA_HOME:-~/.local/share}/claude-account-fallback` (directories 0700, files 0600), outside the repo. `CLAUDE_ACCOUNT_FALLBACK_HOME` overrides that root. Orca must install this plugin into the configuration profile its Claude process uses, and `enable` must target that same directory. The manager does not change Orca's account selector.
