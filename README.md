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

## Credits

The `scrutinize` and `management-talk` skills come from
[thananon/9arm-skills](https://github.com/thananon/9arm-skills) by
[9arm (thananon)](https://github.com/thananon). Thanks for sharing them.

| Plugin | Upstream skill |
| --- | --- |
| `scrutinize` | [`skills/engineering/scrutinize`](https://github.com/thananon/9arm-skills/tree/main/skills/engineering/scrutinize) |
| `management-talk` | [`skills/productivity/management-talk`](https://github.com/thananon/9arm-skills/tree/main/skills/productivity/management-talk) |

## Develop

Plugin files live in `plugins/<name>/`; metadata is generated from `plugin-sources.json`.

```bash
python3 scripts/sync-plugins.py          # regenerate manifests and marketplaces
python3 -m unittest discover -s tests    # verify packaging and generated output
```
