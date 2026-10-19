# plong-agent-toolkit

Shareable skills and hook plugins for **Codex and Claude Code**, published under the
marketplace name `plong-agent-toolkit`. No MCP connections or credentials are bundled.

## Install

Claude Code:

```
/plugin marketplace add Plong-Wasin/plong-agent-toolkit
/plugin install scrutinize@plong-agent-toolkit
```

Codex CLI:

```bash
codex plugin marketplace add Plong-Wasin/plong-agent-toolkit
codex plugin add scrutinize@plong-agent-toolkit
```

Browse the full catalog with `/plugin` (Claude Code) or `/plugins` (Codex).

## Develop

Plugin files live in `plugins/<name>/`; metadata is generated from `plugin-sources.json`.

```bash
python3 scripts/sync-plugins.py          # regenerate manifests and marketplaces
python3 -m unittest discover -s tests    # verify packaging and generated output
```
