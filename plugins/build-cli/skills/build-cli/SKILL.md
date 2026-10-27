---
name: build-cli
description: Plong's approach to building a command-line client (CLI) for an existing service, usually the MCP server or HTTP API of a tool such as GlitchTip - pick the shortcuts from what the user really calls in their Claude Code session history, write TypeScript with zero runtime dependencies split into modules and bundled into one dist file, support several profiles (instances, accounts, OAuth or static token), test it black-box against a fake server, install it from a CI-built `release` branch, and ship a Claude Code + Codex skill that teaches agents to drive it. Use this skill whenever the user wants to make, extend, test, restructure or publish a CLI that wraps an MCP server or API, says "ทำ cli", "wrap the MCP as a CLI", "like glitchtip-cli", or asks to make an existing CLI follow their conventions, even if they never mention a skill.
---

# Build a CLI the Plong way

A CLI here is a **thin client over a service that already exists**, usually an MCP server the user already uses through Claude. The point is reach: the same capability from a shell, a pipe, Codex or a headless job, without giving up anything the server enforces (auth, read-only guards, row caps, audit logs). The reference implementation is `Plong-Wasin/glitchtip-cli`; read its layout when something here is unclear.

## Principles, and why

1. **Client only.** Send the same requests an MCP client would; never add a side door (direct database connection, scraping, a second credential path). The server's guard and audit trail are the reason the CLI is safe to hand to an agent.
2. **Shortcuts come from evidence.** Mine the user's session history first (step 1 below) and give the most-called tools the shortest commands. A command nobody types is clutter; a missing bulk form of the command they type hundreds of times is a bug.
3. **Keep a raw escape hatch.** `info`, `tools`, `call <tool> key=value --args JSON` mean a renamed or new server tool never blocks anyone, and they make the shortcuts testable against `tools/list`.
4. **Zero runtime dependencies.** Node's `parseArgs`, `fetch`, `node:http` and `node:crypto` cover it. A bundler (esbuild) is a build-time devDependency only, so the installed file is one self-contained script.
5. **Write many files, ship one.** The user reads code in the Laravel way: small files with one job. Source is split into modules; the bundler produces a single `dist/<bin>.js` for release. Never let the entry file grow into the whole program.
6. **Profiles and secrets.** Several profiles (hosts, accounts, environments) in one config file at `~/.config/<cli>/config.json`, mode 600; credentials are masked in output and never echoed.
7. **Test black-box.** Run the built file as a child process against a fake server with an isolated `HOME`. This covers argument parsing, transport, auth and exit codes in one pass, and it found real bugs in the first CLI that mocking would have hidden.
8. **Ship an agent skill with it.** The CLI is only useful to agents if a skill says when to use it, which profile is safe, and which commands write. The repo doubles as a Claude Code + Codex plugin marketplace.

## Workflow

### 1. Mine the history to choose the commands

```bash
python3 <this-skill>/scripts/mcp-tool-usage.py glitchtip          # server name as in mcp__<server>__<tool>
```

It prints call counts per tool, the common argument shapes with an example of each, and which projects call it. Read the argument shapes: constants that appear in nearly every call (an org slug, a project, an environment) belong in profile defaults, not flags. Tools called in bursts with one id each (resolve, delete, tag) need a multi-id form.

Record the counts in the README so the next reader sees why the shortcuts exist. The "used in" column shows the user's real project directory names, which are often company or client names: use them to understand the workload, but keep them out of the README, skill and tests. Count `tool_use` blocks as the script does; a raw `grep -c` over the transcripts also matches tool results and attachments and overstates the numbers.

### 2. Settle four things with the user, only if unclear

CLI/bin name (full word unless the user wants an abbreviation), base URL, auth kind (inspect `/.well-known/oauth-authorization-server` and the `WWW-Authenticate` header of an unauthenticated POST to the MCP URL: OAuth means `auth login`, a static bearer means `auth set`), and whether the repo will be public (then no company hostnames, orgs or private repo names anywhere, and a LICENSE).

### 3. Scaffold

Follow `references/layout.md` for the module layout, the module responsibilities and the code patterns that matter (transport and session, 401 refresh, dash-leading flag values, dropping unset arguments). Copy `package.json`, `tsconfig.json` and the CI workflow from `references/distribution.md`.

### 4. Implement in this order

Config and profiles → MCP transport (initialize once, then `tools/call`) → auth (OAuth PKCE with refresh, and/or static token) → read commands → write commands → raw commands → `--help`. Run `pnpm typecheck` after each step; run the built file against a real server only once the user has signed in themselves (an OAuth login needs their browser).

### 5. Write the tests with the code, not after

Follow `references/testing.md`. Every command gets a test of the tool name and arguments it sends; every auth path gets a test; every bug found later gets a regression test. If a test is hard to write, the command is usually doing too much.

### 6. CI and release

Typecheck, test, build, then force-push `main` plus `dist/` to a `release` branch; users install from that branch. Details and the pnpm and npm traps are in `references/distribution.md`.

### 7. Plugin and skill

Add `plugins/<name>/skills/<bin>/SKILL.md` with manifests for both clients and no `version` field (every commit then counts as a new version). For the marketplace mechanics use the `multi-client-plugin` skill. The CLI's skill must cover: install check, profile check, safety rules, the common commands, raw access, exit codes. Update it whenever a command, flag or safety rule changes.

## Command design rules

- **Shape.** `<bin> [-p profile] <command> [args] [flags]`; commands are verbs or nouns the user would say (`issues`, `latest`, `resolve`), not the MCP tool names.
- **Ids are forgiving.** Accept `123`, `#123` and a pasted URL, but reject `abc123`: anchor the pattern so a typo never becomes a different id.
- **Bulk writes.** Take many ids, call once per id, keep going after a failure, print `#id: reason` per failure on stderr, and exit 1 at the end with the count.
- **Write commands are labelled.** Help text and the skill mark them "only on explicit instruction"; read-only is the default posture of every agent that uses the CLI.
- **Output.** Data on stdout, notes and footers on stderr so pipes stay clean. `--json` prints `structuredContent` when the tool has it, otherwise the whole result. Don't invent a table format before seeing real server output.
- **Exit codes.** `0` ok, `1` server/tool/auth error, `2` usage error. Errors print as `<bin>: <message>` and say how to fix it ("Run `<bin> auth login main`").
- **Flags beat env beats profile.** Env names are `<BIN>_PROFILE`, `_TOKEN`, `_ORG`, `_PROJECT`, `_ENV`, `_CONFIG`.
- **Defaults are safe.** If the service has UAT and prod, the profile imported by default is UAT, and the skill says to use prod only when the user asks.

## Gotchas already paid for

- `parseArgs` treats `--sort -count` as two flags. Glue a dash-leading value to its long option (`--sort=-count`) before parsing, but leave real flags alone so `--sort --json` still errors.
- Versions: read `package.json` through a JSON import so the bundler inlines it. A `new URL('../package.json', import.meta.url)` read breaks once everything is one file in `dist/`.
- Imports inside `src/` use the `.js` extension under NodeNext. Test files run through Node's type stripping, so they use `.ts` extensions and erasable syntax only.
- pnpm 12 fails `install --frozen-lockfile` with `ERR_PNPM_IGNORED_BUILDS` until `pnpm-workspace.yaml` sets `allowBuilds: { esbuild: true }`. CI discovers this the hard way.
- `npm install -g git+...#release` needs `--install-links`, or npm 11 leaves a dead symlink to a deleted temp clone.
- `--manual` login mode must close its readline when the loopback redirect wins, or the process never exits.
- Tests must always pass `--manual` for login so no browser opens, scrub inherited env, and use a temp `HOME`.
- Never read another client's stored OAuth tokens (for example Claude Code's) to skip login: refresh-token rotation would sign that client out.
- Before going public, strip company hostnames, org and project slugs from defaults, README, skill description and tests; require `--url` instead of baking in a default host. For the full pre-publish sweep use the `multi-client-plugin` skill's checklist.

## Reference files

- `references/layout.md` — module layout, responsibilities, code patterns.
- `references/testing.md` — fake server, CLI runner, what to cover, how to run.
- `references/distribution.md` — package.json, tsconfig, esbuild, CI release, install commands, README and plugin checklist.
- `scripts/mcp-tool-usage.py` — counts MCP tool calls and argument shapes in `~/.claude/projects/**/*.jsonl`.
