---
name: ai-usage-dashboard
description: Collect AI token usage and cost with ccusage (Claude Code, Codex, and extra Claude config dirs such as a devcontainer's .claude) and render one standalone Cloudflare-style HTML dashboard with filters by source, tool, model and date range. Use whenever the user asks how many tokens or how much money AI usage costs, which model is the most expensive, wants a usage/cost dashboard, wants to merge usage from several .claude folders, or says "ccusage", "ใช้ token เท่าไร", "ราคา model", "ทำ dashboard การใช้ AI", even if they never say "dashboard".
---

# AI usage dashboard

Turn `ccusage` numbers into a single offline HTML page the user can open, filter and print. The page has summary cards, a daily stacked chart by model, tables by source / model / day, and a Cloudflare-style filter bar (field + is / is-not + multi-value chips, plus a date range).

## Workflow

1. **Find every usage source.** ccusage only reads the default Claude folder (and Codex) on its own. Other folders hold separate histories that are silently missing from the totals — typically a devcontainer bind mount such as `<repo>/.devcontainer/.claude` (check `devcontainer.json` for `target=.../.claude`), or another profile's `CLAUDE_CONFIG_DIR`. Ask the user which extra folders matter if it is not obvious; look for `projects/` with `*.jsonl` inside to confirm a folder really has history.
2. **Build the dashboard** with the bundled script (it shells out to `npx ccusage@latest`, so it needs Node and network the first time):

   ```bash
   python3 -I <skill-dir>/scripts/build_dashboard.py \
     --out <path>/ai-token-usage-dashboard.html \
     --source "เครื่องหลัก=" \
     --source "devcontainer=/abs/path/to/.devcontainer/.claude"
   ```

   - The first `--source` with an empty path uses ccusage's defaults and keeps every model, so Codex and other detected agents are counted once there.
   - Every later source contributes Claude models only. Reason: ccusage reports the host's Codex history on every run, so keeping it from extra sources would double count it.
   - Labels are free text shown in the filter and the source table. Write them in the user's language.
3. **Check the output** before reporting: the script prints rows, days and per-source cost. Compare the sum against `npx ccusage@latest daily` for the default source if anything looks off.
4. **Report** to the user: the clickable file link, total and per-source cost, the most expensive model, and the date range of each source (a source's history can end earlier than the others, e.g. a devcontainer no longer in use).

## Real credit vs subscription

When the user wants to know whether a subscription beats paying per token, run `scripts/build_compare.py` (same `--source` flags, plus one `--plan "KEY|LABEL|SHORT|MONTHLY_USD|NOTE"` per tool, KEY = `claude` or `codex`). Find the real plan first instead of guessing: `subscriptionType` in `<config-dir>/.credentials.json`, `oauthAccount` in `.claude.json` (compare `accountUuid` across folders: the same account is one seat, not two), and the `chatgpt_plan_type` claim in the Codex `auth.json` id_token. Never print the tokens themselves. Seat prices are not stored locally, so state the price you used as an assumption; the page lets the reader edit it.

## What to tell the user about the numbers

The cost is ccusage's estimate at pay-per-token API rates. A subscription user does not pay that amount, so present it as a way to compare models and periods, not as an invoice. The page repeats this caveat; keep it when editing the template.

## Customising

`assets/template.html` is the whole UI (inline CSS and JS, no CDN, light and dark theme, print CSS). Placeholders `__DATA__`, `__LABELS__`, `__NOTE__`, `__GEN__` are filled by the script. Add a new filter field by adding a key to `FIELDS` in the template and the same key on each row in `build_dashboard.py`. The data is a snapshot: rerun the script to refresh.

## Output location

Use the path the user gives. Without one, a gitignored scratch folder such as the repo's `.local/` is a reasonable default; the file embeds usage figures, so do not commit or share it unless asked.
