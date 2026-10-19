---
name: plong-statusline
description: "Install plong's Claude Code statusline: model and effort, directory, git branch, context window %, and the 5-hour / weekly plan usage with reset times, turning red with a warning mark at 90%. Arguments: install (default), status, uninstall."
argument-hint: "[install|status|uninstall]"
disable-model-invocation: true
---

# Plong statusline

The user ran this command to change their own Claude Code statusline, so carry out the requested action instead of only describing it.

The statusline renders one line:

```
Opus 5.5 · high in my-repo (feature-x) ctx:42% 5h:78%→16:00 wk:74%→Sat 16:00
```

It needs `bash`, `jq`, `git`, and GNU `date`. The 5h / wk parts appear only when Claude Code receives plan usage, which happens with a claude.ai subscription.

## Run

The action is `$ARGUMENTS`; when that is empty, use `install`. Run the script in this skill's base directory:

```bash
bash <this skill's base directory>/scripts/setup.sh <install|status|uninstall>
```

- `install` copies the statusline to `~/.local/share/plong-statusline/statusline.sh` and points `statusLine.command` in `~/.claude/settings.json` at it. It saves the previous command and backs up settings.json to that folder first. Re-running it is safe: it only refreshes the script.
- If the usage-guard-statusline wrapper already owns `statusLine.command`, `install` leaves settings.json alone. It sets this statusline as the wrapper's inner command instead, so the usage guard keeps reading plan usage and this statusline is what the user sees.
- `status` shows where it is installed and whether the installed copy matches the plugin.
- `uninstall` restores the previous command, or removes `statusLine` when there was none.

Let the script make the change rather than editing settings.json by hand. It validates the JSON and keeps a backup. It refuses to touch an invalid settings.json; if that happens, report it and stop.

The plugin's SessionStart hook keeps the installed copy in sync with plugin updates. Customizations belong in `scripts/statusline.sh` in the plugin source, not in the installed copy, which the next sync overwrites.

Report the outcome to the user in their language:
- what changed;
- the previous statusline command;
- how to undo it (`uninstall`).
