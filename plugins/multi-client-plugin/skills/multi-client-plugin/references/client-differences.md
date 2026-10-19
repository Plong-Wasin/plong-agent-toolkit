# Claude Code vs Codex CLI: what differs

Verified against Codex CLI 0.162.1 and Claude Code 2.1.x. Re-verify after upgrading either
client; the layout below is a compatibility choice, not a spec guarantee.

| Concern | Claude Code | Codex CLI |
|---|---|---|
| Marketplace catalog | `.claude-plugin/marketplace.json` | `.agents/plugins/marketplace.json` |
| Plugin manifest | `plugins/<name>/.claude-plugin/plugin.json` | `plugins/<name>/.codex-plugin/plugin.json` |
| Catalog entry | `name`, `source`, `description` | `name`, `source`, `policy`, `category` (no description) |
| Catalog policy | none | `{"installation": "AVAILABLE", "authentication": "ON_INSTALL"}` |
| Manifest extras | none | `interface`: `displayName`, `shortDescription`, `developerName`, `category`, `capabilities` |
| Inline hooks | event map directly: `"hooks": {"PreToolUse": [...]}` | wrapped: `"hooks": {"hooks": {"PreToolUse": [...]}}` |
| Skills | `skills/<name>/SKILL.md` | same files, same layout |
| Install | `/plugin install x@market` | `codex plugin add x@market` |
| Refresh | `/plugin marketplace update` | `codex plugin marketplace upgrade` |

## Why the manifests live in client folders

A single portable `plugin.json` at the plugin root did not expose plugin hooks in Codex
0.162.1: skills loaded, hooks silently did not. Keeping one manifest per client folder and
**no** root `plugin.json` is what made hooks load, so the generator never emits a root manifest
and the tests assert it is absent.

## Hook behaviour to design for

- `${CLAUDE_PLUGIN_ROOT}` in a hook command is resolved by both clients; after discovery a
  command containing a literal `${` means the path failed to resolve.
- Fresh Codex installs list hooks as `untrusted`; the user must review them. Do not treat that
  as a bug.
- Hook input and output fields are not identical across clients. Test each client's command with
  synthetic JSON and mark a hook `"clients": ["claude"]` if it needs Claude-only fields.
- A deny is signalled by exit code 2 or a JSON `permissionDecision: deny` on stdout; accept both
  when writing tests.

## Caches

Both clients cache installed plugins by version. Editing a repo does not update an installed
copy; the content hash in the generated version string is what forces a refresh. After a
marketplace refresh users must update or reinstall the plugin and open a new session.
