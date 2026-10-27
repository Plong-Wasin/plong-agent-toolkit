# Build, release and publish

## package.json

```json
{
  "name": "<bin>-cli",
  "version": "0.1.0",
  "description": "...",
  "type": "module",
  "bin": { "<bin>": "./dist/<bin>.js" },
  "scripts": {
    "typecheck": "tsc --noEmit && tsc --noEmit -p tsconfig.test.json",
    "build": "pnpm typecheck && esbuild src/index.ts --bundle --platform=node --target=node20 --format=esm --banner:js=\"#!/usr/bin/env node\" --outfile=dist/<bin>.js && chmod +x dist/<bin>.js",
    "test": "pnpm build && node --test \"test/*.test.ts\""
  },
  "engines": { "node": ">=20" },
  "devDependencies": { "@types/node": "^20", "esbuild": "...", "typescript": "..." },
  "private": true,
  "license": "MIT"
}
```

`private: true` only stops an accidental `npm publish`; it does not affect installing from git. No `dependencies`.

`tsconfig.json`: `target ES2022`, `module`/`moduleResolution` `NodeNext`, `lib ES2023`, `types ["node"]`, `noEmit`, `resolveJsonModule`, `strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `skipLibCheck`, `include ["src"]`. tsc only typechecks; esbuild produces the output.

`pnpm-workspace.yaml` (pnpm 12 refuses to install otherwise):

```yaml
allowBuilds:
  esbuild: true
```

`.gitignore`: `node_modules/`, `dist/`, `.scratch/`, `*.local.*`, `.local/`.

## CI release (`.github/workflows/release.yml`)

On push to `main`: checkout, `pnpm/action-setup`, Node 24 with pnpm cache, `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm test`, `pnpm build`, then publish `main` plus `dist/` to the `release` branch:

```yaml
permissions: { contents: write }
concurrency: { group: release, cancel-in-progress: true }
# ...
      - run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git checkout --detach
          git add -f dist
          git commit -m "Release build of ${GITHUB_SHA::7}"
          git push --force origin HEAD:refs/heads/release
```

`release` is force-pushed by this workflow only; nobody commits to it by hand. `dist/` never lands on `main`. The first install works only after the first workflow run has created the branch.

## Install commands for the README

```sh
# public repo
npm install -g --install-links git+https://github.com/<owner>/<repo>.git#release
# private repo
npm install -g --install-links git+ssh://git@github.com/<owner>/<repo>.git#release
```

`--install-links` is required: without it npm 11 symlinks the global install to a temporary clone that it deletes. Re-running the same command updates. From source: `pnpm install && pnpm build && pnpm link --global`.

## README sections

What it is and what stays on the server; Install; first login (`auth login --url ... --org ... --project ...`); Usage with real examples; Multiple profiles; env overrides and exit codes; command-to-tool map with the usage counts that justified the shortcuts; Development (layout tree, `pnpm test`, note that tests never touch a real server or the real config); Agent skill install for both clients.

## Agent skill and plugin

```
.claude-plugin/marketplace.json
.agents/plugins/marketplace.json
plugins/<bin>-cli/.claude-plugin/plugin.json
plugins/<bin>-cli/.codex-plugin/plugin.json
plugins/<bin>-cli/skills/<bin>/SKILL.md
```

Manifests carry no `version`. Claude Code installs with `/plugin marketplace add <owner>/<repo>` and `/plugin install <name>@<marketplace>`; Codex with `codex plugin marketplace add https://github.com/<owner>/<repo>.git` and `codex plugin add ...`. The plugin does not bundle the binary, so the skill's first step is `<bin> --version` and the install command. `AGENTS.md` carries the repo rules (modules, no side doors, smoke tests only against safe environments, update the skill with every command change, `pnpm typecheck && pnpm test` before committing) and `CLAUDE.md` is the single line `@AGENTS.md`.

## Going public

Choose a license (MIT unless told otherwise) and add `LICENSE`, `package.json` and plugin manifest `license`. Remove company hostnames, org and project slugs, internal repo names and the author's private paths from source defaults, README, skill, tests and eval fixtures; examples use `glitchtip.example.com`, `my-org`, `my-project`. Require `--url` rather than a baked-in default host. Then run the full sweep from the `multi-client-plugin` skill. Publishing is hard to undo, so ask before the first push.
