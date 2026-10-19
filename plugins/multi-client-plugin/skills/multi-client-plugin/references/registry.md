# plugin-sources.json

```json
{
  "name": "my-marketplace",
  "owner": {"name": "me"},
  "metadata": {"description": "…", "version": "1.0.0"},
  "plugins": [ … ]
}
```

`name` is the marketplace name (used in `plugin@name`). `metadata.version` is the prefix of
every generated plugin version (`1.0.0+<content hash>`).

## Local plugin (files in this repo)

```json
{
  "name": "lock-hook",
  "description": "One sentence shown in the catalog",
  "clients": ["claude", "codex"],
  "skills": ["./skills/my-skill"],
  "files": ["hook-scripts/check.sh"],
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{"type": "command",
                 "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hook-scripts/check.sh\"",
                 "statusMessage": "lock-hook: checking"}]
    }]
  },
  "compatibilityNote": "Optional: why a client is excluded"
}
```

- `skills` paths are relative to `plugins/<name>/` and must start with `skills/`.
- `files` lists hook scripts and other resources that belong in the package. A hook command
  that references an undeclared or missing file makes generation fail on purpose.
- Plugin names are lowercase kebab-case and unique.
- Give hooks a readable `statusMessage`; Codex's hook browser shows it.

## External plugin (hosted in another repo)

```json
{
  "name": "other-plugin",
  "description": "…",
  "clients": ["claude", "codex"],
  "source": {"source": "git-subdir",
             "url": "https://github.com/owner/repo.git",
             "path": "plugins/other-plugin",
             "ref": "main"}
}
```

Both catalogs reference it; nothing is generated. Use an SSH url for a private repo. Claude
entries may add extra marketplace fields through a `marketplace` object (for example
`strict: false` with a skills subset of an upstream repo).

## Generated output

The generator writes both marketplace catalogs, every `plugins/<name>/.{claude,codex}-plugin/plugin.json`,
and `plugins/generated-files.json`, which records what it owns so that removing a client or
plugin deletes only stale metadata, never skill or hook sources.
