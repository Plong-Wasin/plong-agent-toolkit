---
name: multi-client-plugin
description: Build, restructure, or debug a plugin and marketplace repo that installs in several agent clients at once (Claude Code and Codex CLI) from a single set of skill and hook sources. Use whenever the user wants to make a plugin work in both Claude Code and Codex, add Codex support to a Claude plugin (or the reverse), generate .claude-plugin / .codex-plugin manifests and marketplace.json / .agents/plugins/marketplace.json from one registry, split a personal marketplace into shareable and private parts, reference a plugin that lives in another repo, or find out why a hook or skill does not show up in one client. Trigger even if they only say "support codex too", "one repo for all my agent plugins", or "multi-client marketplace".
---

# Multi-client plugin repo

One repo, one editable copy of every skill and hook, generated metadata for each client.
The editable files are the source of truth; only manifests and catalogs are generated, so
there is never a second copy of a skill to drift out of sync.

Read `references/client-differences.md` before writing any manifest by hand, and
`references/registry.md` for the registry fields. Both explain *why* each rule exists.

## Layout

```
repo/
├── plugin-sources.json            # the only hand-edited metadata
├── scripts/sync-plugins.py        # generator (template: scripts/sync-plugins.py in this skill)
├── tests/test_plugins.py          # drift + packaging checks
├── .claude-plugin/marketplace.json   # generated
├── .agents/plugins/marketplace.json  # generated (Codex)
└── plugins/<plugin>/
    ├── skills/<skill>/SKILL.md    # editable, shared by both clients
    ├── hook-scripts/…             # editable, optional
    ├── .claude-plugin/plugin.json # generated
    └── .codex-plugin/plugin.json  # generated
```

One plugin per installable unit. Keep skill names unique across the repo, because users who
link skills globally would otherwise see duplicates.

## Workflow

1. **Decide the clients per plugin.** A plugin that relies on a client-only feature (for
   example Claude-specific hook payload fields) gets `"clients": ["claude"]` and a
   `compatibilityNote`; do not ship a Codex entry that cannot work.
2. **Write sources** under `plugins/<name>/skills/<skill>/` (and `hook-scripts/`). Hook commands
   refer to files with `${CLAUDE_PLUGIN_ROOT}/…`; the generator checks that each referenced
   file exists and is declared.
3. **Declare the plugin** in `plugin-sources.json` (see `references/registry.md`).
4. **Generate**: copy `scripts/sync-plugins.py` into the repo if it is not there, adjust the
   display name, then run `python3 scripts/sync-plugins.py` and commit the output with the
   sources. Generated files are checked in so installing from GitHub needs no build step.
5. **Verify**: `python3 scripts/sync-plugins.py --check` and the unit tests. If both CLIs are
   installed, also install into a disposable `CODEX_HOME` and inspect discovery; unit tests
   alone cannot prove that a client loads a hook.
6. **Publish**, then tell users to refresh (`/plugin marketplace update <name>` in Claude Code,
   `codex plugin marketplace upgrade <name>` in Codex) and start a new session.

## Rules that matter

- **Never hand-edit generated files.** Edit the registry or the sources and re-run the
  generator; `--check` fails CI on drift.
- **Marketplace and repo names must be unique and stable.** The marketplace name is part of
  every install id (`plugin@marketplace`); renaming it forces users to reinstall.
- **Plugins in other repos** use a `source` object (`git-subdir` or `github`) instead of
  `skills`. Nothing is copied or generated for them, so a user can keep a single marketplace
  that points at plugins hosted elsewhere. A private source only installs for people whose git
  credentials can read it, and its name, description and URL are visible to anyone who can
  read the marketplace.
- **The generated version contains a content hash**, so edited sources invalidate client caches.
  Do not set versions by hand.
- **Codex hooks are untrusted on first install.** That is expected; test hook commands by
  piping synthetic JSON into them instead of waiting for trust.

## Before making the repo public

Publishing is irreversible in practice (forks, caches). Read every file of every plugin; a
grep pass is not enough, because secrets and private context do not look like secrets. Real
examples that grep missed: a notification topic that acts as a password, an internal
project name inside an eval fixture, the author's office network described in a case study,
and a build cache (`__pycache__`) containing a home path. Check for:

- credentials, tokens, and URL path segments that act as secrets (webhook or topic ids)
- personal data: names, emails, home paths, hostnames, device and network identifiers
- internal company, client, project, and ticket names, including in tests and evals
- real incidents or vulnerabilities from private code used as examples
- `__pycache__`, logs, and local settings; add them to `.gitignore` before the first commit

Replace what you find with placeholders or environment variables, or leave that plugin out of
the public repo. If it already shipped in git history, rewrite the history or rotate the secret.
