---
name: commit
description: >
  Create a git commit with an auto-generated message based on staged/unstaged changes,
  then optionally push. Use this skill whenever the user wants to commit, save changes
  to git history, or says things like "commit this", "save my changes", "บันทึก", "คอมมิต".
  Also trigger when the user finishes a task and the work should be recorded in git.
---

# Git Commit

## Step 1: Understand the current state

Run in parallel to get a full picture before touching anything:

```bash
git status
git diff --staged
git diff
git log --oneline -5
```

Look at what's changed and why — this informs both which files to stage and what the commit message should say.

## Step 2: Stage specific files

Stage only relevant files by name. Avoid `git add .` or `git add -A` — they can accidentally include sensitive files, generated artifacts, or unrelated work.

```bash
git add path/to/file1 path/to/file2
```

Skip: `.env`, credentials, API keys, large binaries, build output.

## Step 3: Commit

Use a heredoc to avoid shell quoting issues:

```bash
git commit -m "$(cat <<'EOF'
type: short description

Optional body explaining why.
EOF
)"
```

Then verify:
```bash
git status
```

## Commit Message Format

**Subject** (first line): ≤50 chars, imperative mood, conventional prefix

| Prefix | When to use |
|--------|-------------|
| `feat` | new capability |
| `fix` | bug fix |
| `docs` | documentation only |
| `refactor` | restructuring without behavior change |
| `chore` | maintenance, deps, config |

Examples:
- `feat: add export to CSV option`
- `fix: handle empty response from API`
- `docs: update setup instructions`

**Body** (optional): explain *why*, not *what*. Wrap at 72 chars.

## Rules

- If a pre-commit hook fails → fix the issue, then create a **new** commit. Never use `--amend` after a failed hook, never use `--no-verify`
- Do not add `Co-Authored-By:` trailers unless the user explicitly asks
- Ask before pushing — do not push automatically unless the user said to
