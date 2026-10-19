---
name: laravel-worktree-bootstrap
description: Prepare a Laravel Git worktree before implementation or testing by checking isolation, installing worktree-local Composer dependencies, wiring .env.testing, and validating ignored runtime files.
---

# Laravel Worktree Bootstrap

Use this skill after creating or entering a Laravel Git worktree and before running Artisan, Composer, or test commands.

## 1. Identify the worktree

Run these commands from the intended worktree:

```bash
git rev-parse --show-toplevel
git status --short --branch
git worktree list
```

Read the nearest `AGENTS.md`, `composer.json`, `.gitignore`, and `phpunit.xml` or `phpunit.xml.dist`. Record the worktree path, branch, base branch, and repository-specific test command. A worktree is ready for the next step when its root and branch are unambiguous and its local instructions are known.

Keep the worktree as a sibling of the main checkout. A nested worktree makes ignored runtime files and relative paths harder to reason about.

## 2. Prepare Composer dependencies

Make `vendor/` local to this worktree so Composer's generated autoload paths resolve to this checkout's source files.

```bash
test -f vendor/autoload.php && echo 'vendor ready' || echo 'vendor missing'
```

When `vendor/autoload.php` is missing, run from the worktree:

```bash
composer install --no-interaction --prefer-dist --no-progress --no-scripts
composer dump-autoload --no-scripts
```

If a trusted checkout already has a compatible `vendor/`, copy it into the worktree and regenerate the autoloader there. A `vendor/` symlink to another worktree is not a valid completed state; inspect its target, prepare a local directory, and regenerate autoload files before testing. Keep the source checkout's `vendor/` intact.

Run Composer scripts only when the repository instructions or the task requires them. This keeps bootstrap focused and avoids application-side mutations during dependency setup.

The dependency step is complete when `vendor/autoload.php` exists in the current worktree and `composer dump-autoload --no-scripts` succeeds there.

## 3. Select the test environment

Use `.env.testing` for PHPUnit and Artisan test commands. Check that it exists without printing its contents:

```bash
test -f .env.testing && echo '.env.testing ready' || echo '.env.testing missing'
git check-ignore -v .env.testing || true
```

When the file is maintained by another local checkout, create an explicit symlink to that absolute path, for example:

```bash
ln -s /absolute/path/to/source/.env.testing .env.testing
```

Preserve an existing `.env.testing` file or symlink after checking that it points to the intended configuration. Keep `.env` outside the test setup: do not create, copy, select, or edit `.env` for tests. If `.env.testing` is unavailable, report the missing prerequisite instead of silently falling back to `.env` or inventing database credentials.

Confirm the test runner sets `APP_ENV=testing` through `phpunit.xml` or the repository's documented command. Never echo environment values, connection strings, tokens, or credentials.

The environment step is complete when `.env.testing` is readable, its source is identified, and the planned test command selects `testing` explicitly.

## 4. Check other ignored runtime state

Inspect the repository's `.gitignore` and prepare only the runtime state the application or task needs:

- `storage/` and `bootstrap/cache/`: create missing Laravel runtime directories locally.
- `public/storage`: create the Laravel storage link only when the task exercises public storage.
- `node_modules/`: run `npm ci` in this worktree only when frontend assets or a repository command requires it; use the lockfile selected by the repository.
- framework caches, test result files, and local logs: keep them ignored and scoped to this worktree.

Do not copy ignored state wholesale. Each copied or generated item must have a known purpose and a worktree-local path. This step is complete when required runtime paths exist and optional paths are either prepared or explicitly out of scope.

## 5. Validate and hand off

Run the smallest relevant checks first, then the repository's proportionate test command. In this Laravel repository, prefer parallel execution with about half of the available CPUs, for example:

```bash
php artisan test --parallel --processes=8 tests/Feature/SomeTest.php
```

`php artisan test` accepts one path per invocation; use separate commands, a directory, or `--filter` for multiple targets. Let the repository's `AGENTS.md` override the example process count. Use the existing `.env.testing` database configuration and preserve the first database exception when a later rollback or cleanup error also appears.

Finish with:

```bash
git status --short --branch
git check-ignore -v vendor .env.testing storage bootstrap/cache || true
```

The worktree is ready when all of the following are true:

- the current root and branch are the intended worktree;
- Composer dependencies and autoload files are local to it;
- `.env.testing` is the selected test environment and `.env` was not used;
- required runtime state is present and ignored;
- relevant validation results and any external blockers are reported; and
- `git status` shows only intentional source changes.
