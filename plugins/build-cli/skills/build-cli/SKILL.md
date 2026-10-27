---
name: build-cli
description: Plong's approach to building a command-line client (CLI) for an existing service, over its REST API (preferred when one exists) or its MCP server - decide which transport to use, pick the shortcuts from what the user really calls in their Claude Code session history, write TypeScript with zero runtime dependencies split into modules and bundled into one dist file, support several profiles (instances, accounts, API token or OAuth), test it black-box against a fake server, install it from a CI-built `release` branch, and ship a Claude Code + Codex skill that teaches agents to drive it. Use this skill whenever the user wants to make, extend, test, restructure or publish a CLI that wraps an API or MCP server, says "ทำ cli", "wrap the MCP as a CLI", "ใช้ api แทน mcp", "like glitchtip-cli", or asks to make an existing CLI follow their conventions, even if they never mention a skill.
---

# Build a CLI the Plong way

A CLI here is a **thin client over a service that already exists**. The point is reach: the same capability from a shell, a pipe, Codex or a headless job, without giving up anything the server enforces (auth, read-only guards, row caps, audit logs). The reference implementation is `Plong-Wasin/glitchtip-cli`; read its layout when something here is unclear.

It started as an MCP client and was rewritten over the REST API once the MCP tools turned out too narrow (no delete, no bulk change, no comments, no pagination). That is why the first decision below exists: do not default to MCP just because the user's agent already talks to it.

## MCP or REST? Decide first

Prefer the **REST API** when the service has one and the user can get an API token. Use **MCP** only when it is the only programmatic surface (no public API, or the API is not reachable with a token you can create) or when its tools are exactly what the user needs.

| | REST API | MCP endpoint |
|---|---|---|
| Coverage | The whole product: every list, filter, bulk and destructive endpoint, pagination | Only the tools the server author chose to expose, often read-heavy |
| Auth | A bearer API token the user creates in the web UI; no browser flow, no refresh, works headless | Usually OAuth with PKCE and rotating refresh tokens; some servers have no OAuth discovery at all |
| Self-hosted servers you do not run | Works if the API is enabled | May be disabled, behind another gateway, or lack `.well-known` |
| Schema | OpenAPI (`/api/openapi.json`, `/docs`), so you can check shapes instead of guessing | `tools/list`, shapes only as good as the descriptions |
| Cost to build | Per-endpoint code, but plain `fetch` and JSON | Small, but a session handshake, SSE parsing and OAuth |

How to decide in practice:

1. Fetch the OpenAPI document (`<base>/api/openapi.json`, `/openapi.json`, `/swagger.json`) and look at the paths. Probe an unauthenticated call: `401 {"detail":...}` with a bearer scheme means token auth works.
2. List what the user actually does (step 1 of the workflow) and mark which of those the MCP tools cannot do. One or two gaps (bulk, delete, comments, pagination) is enough reason to go REST.
3. Ask the user which they want only when both are viable and it is not obvious. If they say MCP "does not meet the need", go REST without further debate and delete the MCP transport instead of keeping both: two transports double the tests and the docs.

Mining MCP usage still helps when moving to REST: the tools the user called most are the commands that need the shortest shortcuts, and the gaps they worked around are the new features.

## Principles, and why

1. **Client only.** Send the same requests the product's own API clients would; never add a side door (direct database connection, scraping, a second credential path). The server's guard and audit trail are the reason the CLI is safe to hand to an agent.
2. **Shortcuts come from evidence.** Mine the user's session history first (step 1 below) and give the most-called operations the shortest commands. A command nobody types is clutter; a missing bulk form of the command they type hundreds of times is a bug.
3. **Keep a raw escape hatch.** REST: `api <METHOD> <path> [key=value] [--data JSON|@file|-] [--all]`. MCP: `info`, `tools`, `call <tool> key=value --args JSON`. A missing shortcut or a new endpoint then never blocks anyone, and the shortcuts stay checkable against the schema.
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

It prints call counts per tool, the common argument shapes with an example of each, and which projects call it. Read the argument shapes: constants that appear in nearly every call (an org slug, a project, an environment) belong in profile defaults, not flags. Tools called in bursts with one id each (resolve, delete, tag) need a multi-id form, and a burst that repeats one search is asking for a bulk-by-query form.

This works even when the final CLI is REST: the history shows what the user does, whatever the transport was.

Record the counts in the README so the next reader sees why the shortcuts exist. The "used in" column shows the user's real project directory names, which are often company or client names: use them to understand the workload, but keep them out of the README, skill and tests. Count `tool_use` blocks as the script does; a raw `grep -c` over the transcripts also matches tool results and attachments and overstates the numbers.

### 2. Settle four things with the user, only if unclear

CLI/bin name (full word unless the user wants an abbreviation), base URL, transport and auth (see "MCP or REST?"; REST means `auth set` with an API token, MCP with OAuth means `auth login`: inspect `/.well-known/oauth-authorization-server` and the `WWW-Authenticate` header of an unauthenticated POST to the MCP URL), and whether the repo will be public (then no company hostnames, orgs or private repo names anywhere, and a LICENSE).

### 3. Scaffold

Follow `references/layout.md` for the module layout, the module responsibilities and the code patterns that matter (REST client and pagination, or MCP transport and session; 401 handling, dash-leading flag values, dropping unset arguments). Copy `package.json`, `tsconfig.json` and the CI workflow from `references/distribution.md`.

### 4. Implement in this order

REST: config and profiles → client (`api()` with bearer token, error mapping, cursor pagination) → `auth set` / `auth check` → read commands → write commands → raw `api` command → `--help`. MCP: config and profiles → MCP transport (initialize once, then `tools/call`) → auth (OAuth PKCE with refresh, and/or static token) → read, write, raw commands → `--help`. Run `pnpm typecheck` after each step; run the built file against a real server only once the user has created a token or signed in themselves, and say plainly that the fake server could not prove real response shapes.

### 5. Write the tests with the code, not after

Follow `references/testing.md`. Every command gets a test of the request it sends (method, path, query, body for REST; tool name and arguments for MCP); every auth path gets a test; every bug found later gets a regression test. If a test is hard to write, the command is usually doing too much.

### 6. CI and release

Typecheck, test, build, then force-push `main` plus `dist/` to a `release` branch; users install from that branch. Details and the pnpm and npm traps are in `references/distribution.md`.

### 7. Plugin and skill

Add `plugins/<name>/skills/<bin>/SKILL.md` with manifests for both clients and no `version` field (every commit then counts as a new version). For the marketplace mechanics use the `multi-client-plugin` skill. The CLI's skill must cover: install check, profile check, safety rules, the common commands, raw access, exit codes. Update it whenever a command, flag or safety rule changes.

## Command design rules

- **Shape.** `<bin> [-p profile] <command> [args] [flags]`; commands are verbs or nouns the user would say (`issues`, `latest`, `resolve`), not endpoint paths or MCP tool names.
- **Ids are forgiving.** Accept `123`, `#123` and a pasted URL, but reject `abc123`: anchor the pattern so a typo never becomes a different id.
- **Bulk writes.** Take many ids, call once per id, keep going after a failure, print `#id: reason` per failure on stderr, and exit 1 at the end with the count.
- **Mass changes by query are guarded.** When the API can change or delete everything matching a search, expose it as `--query <q>` but require `--yes`; without it, list what would change and exit 2. `delete` always requires `--yes`. Combining ids with `--query` is a usage error.
- **Pagination.** Lists default to a sane page, print `more available: --cursor X (or --all)` on stderr, and `--all` follows the cursor with a hard page cap. Confirm the real cursor format (`Link` header, `next` field) against the server before trusting it.
- **Write commands are labelled.** Help text and the skill mark them "only on explicit instruction"; read-only is the default posture of every agent that uses the CLI.
- **Output.** Data on stdout, notes and footers on stderr so pipes stay clean. `--json` prints the raw API response (MCP: `structuredContent` when the tool has it, otherwise the whole result). Default output is a compact table or key/value block, not a JSON dump; keep it plain so an agent can read it.
- **Exit codes.** `0` ok, `1` server/API/auth error, `2` usage error (including a write refused for lack of `--yes`). Errors print as `<bin>: <message>` and say how to fix it ("Check the API token (`<bin> auth check`)"). Map 401/403/404/429 to specific messages that include the method and path; strip a trailing period from the server's `detail` before adding your own punctuation.
- **Flags beat env beats profile.** Env names are `<BIN>_PROFILE`, `_TOKEN`, `_ORG`, `_PROJECT`, `_ENV`, `_CONFIG`.
- **Defaults are safe.** If the service has UAT and prod, the profile imported by default is UAT, and the skill says to use prod only when the user asks.

## Gotchas already paid for

- `parseArgs` treats `--sort -count` as two flags. Glue a dash-leading value to its long option (`--sort=-count`) before parsing, but leave real flags alone so `--sort --json` still errors.
- Versions: read `package.json` through a JSON import so the bundler inlines it. A `new URL('../package.json', import.meta.url)` read breaks once everything is one file in `dist/`.
- Imports inside `src/` use the `.js` extension under NodeNext. Test files run through Node's type stripping, so they use `.ts` extensions and erasable syntax only.
- pnpm 12 fails `install --frozen-lockfile` with `ERR_PNPM_IGNORED_BUILDS` until `pnpm-workspace.yaml` sets `allowBuilds: { esbuild: true }`. CI discovers this the hard way.
- `npm install -g git+...#release` needs `--install-links`, or npm 11 leaves a dead symlink to a deleted temp clone.
- REST: accept pasted tokens with a leading `Bearer `, strip it, and normalise the stored base URL (no trailing slash, no `/api`, `/api/0` or `/mcp`) so a copied URL still works. Let `<BIN>_URL` + `<BIN>_TOKEN` work without any profile for CI and agents.
- REST: an empty body (`204`) is a success, not a JSON parse error; and a mass-change endpoint filtered by a project slug usually wants the numeric project id, so look it up first.
- MCP only: `--manual` login mode must close its readline when the loopback redirect wins, or the process never exits; login tests must always pass `--manual` so no browser opens.
- Tests scrub inherited env and use a temp `HOME`.
- Never read another client's stored OAuth tokens (for example Claude Code's) to skip login: refresh-token rotation would sign that client out.
- Before going public, strip company hostnames, org and project slugs from defaults, README, skill description and tests; require `--url` instead of baking in a default host. For the full pre-publish sweep use the `multi-client-plugin` skill's checklist.

## Reference files

- `references/layout.md` — module layout, responsibilities, code patterns for both transports.
- `references/testing.md` — fake REST or MCP server, CLI runner, what to cover, how to run.
- `references/distribution.md` — package.json, tsconfig, esbuild, CI release, install commands, README and plugin checklist.
- `scripts/mcp-tool-usage.py` — counts MCP tool calls and argument shapes in `~/.claude/projects/**/*.jsonl`.
