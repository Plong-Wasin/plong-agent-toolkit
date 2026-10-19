---
name: laravel-test-filter
description: >
  Build the correct `php artisan test` command for running a specific subset of test
  classes/files (not the whole suite) together with `--parallel --processes=N`. Use this
  whenever the user wants to run only some Laravel/PHPUnit tests — by class name, by
  method, by folder, or across scattered folders — especially in parallel mode. Also use
  it when a `php artisan test` command with multiple file paths fails with
  `Too many arguments, expected arguments "path"`, or when duplicate class names across
  namespaces cause the wrong tests to run.
---

# Laravel Test Filter

`php artisan test` accepts exactly **one** positional `path` argument. Passing several
file paths on the command line (`php artisan test tests/A.php tests/B.php`) always fails
with `Too many arguments, expected arguments "path"` — this isn't a parallel-mode quirk,
it's true with or without `--parallel`. Picking the right one of these techniques avoids
that error and avoids accidentally running the whole suite.

**Argument order matters with `--parallel`**: when a single file or folder path is
involved, put it *after* the options, not before:

```bash
# ✅ correct — path after the options
php artisan test --parallel --processes=8 tests/Feature/WorkspaceA/CreateTest.php

# ❌ wrong — path before --parallel/--processes
php artisan test tests/Feature/WorkspaceA/CreateTest.php --parallel --processes=8
```

## Decision guide

Pick based on where the target tests live, not on how many there are:

1. **All targets share one folder** → pass that folder as the single `path` argument.
   Cleanest option — no filter syntax to get wrong.
2. **Targets are scattered across folders, few enough to name** → use `--filter` with a
   regex alternation of class (or FQCN) names.
3. **The same subset gets re-run often** → define a PHPUnit `<testsuite>` in
   `phpunit.xml` that groups the folders, and run it with `--testsuite=<name>`.

All three combine freely with `--parallel --processes=N`.

## 1. Same folder → pass the folder

```
tests/Feature/Checkout/
├── OrderTest.php
├── CartTest.php
└── PaymentTest.php
```

```bash
php artisan test --parallel --processes=8 tests/Feature/Checkout
```

## 2. Scattered files → `--filter` with alternation

`--filter` matches against test/class names, not file paths, so it doesn't matter which
folders the files are actually in:

```bash
php artisan test --parallel --processes=8 --filter='OrderTest|CartTest|PaymentTest'
```

```bash
# ❌ does not work — only one positional path is accepted
php artisan test tests/Feature/OrderTest.php tests/Feature/CartTest.php --parallel --processes=8
```

Wrapping the alternation in parentheses is optional and only matters once you start
combining it with other regex, e.g. anchoring or a trailing `::method`:

```bash
php artisan test --parallel --processes=8 --filter='(OrderTest|CartTest|PaymentTest)'
```

### Duplicate class names across namespaces

A bare class name in `--filter` matches by name only — if `CreateTest` exists in two
namespaces, filtering on `CreateTest` runs both when you likely wanted one. Use the
fully-qualified class name (FQCN) instead, escaping the namespace backslashes for the
shell:

```bash
php artisan test --parallel --processes=8 \
  --filter='Tests\\Feature\\WorkspaceA\\CreateTest|Tests\\Feature\\WorkspaceB\\CreateTest'
```

The namespace declared *inside* the file is what `--filter` matches against — not the
folder path. If a project's folder layout doesn't mirror its namespaces 1:1 (common when
tests are organized by "workspace" or feature area rather than by PSR-4 convention),
check the `namespace` line in the file rather than assuming it from the path.

### Single method within a class

Append `::method_name` to the FQCN, same alternation pattern:

```bash
php artisan test --parallel --processes=8 \
  --filter='Tests\\Feature\\WorkspaceA\\CreateTest::test_can_create|Tests\\Feature\\WorkspaceB\\CreateTest::test_can_create'
```

## 3. Recurring subset → PHPUnit testsuite

For a subset that gets run repeatedly (a "smoke" set, a module's tests spread across
several directories), encode it once in `phpunit.xml` instead of retyping a filter every
time:

```xml
<testsuites>
    <testsuite name="partial">
        <directory>tests/Feature/Order</directory>
        <directory>tests/Feature/Promotion</directory>
        <file>tests/Unit/Payment/PaymentTest.php</file>
    </testsuite>
</testsuites>
```

```bash
php artisan test --testsuite=partial --parallel --processes=8
```

This is the only clean way to combine multiple *folders* in one run — `php artisan test`
has no equivalent of passing several directory paths directly.

## Quick reference

| Situation | Command shape |
|---|---|
| One folder or file, path required | `php artisan test --parallel --processes=N <path>` (path *after* the options) |
| A few named classes, any location | `php artisan test --parallel --processes=N --filter='A\|B\|C'` |
| Duplicate class names across namespaces | `--filter='Full\\Namespace\\A\|Full\\Namespace\\B'` (FQCN) |
| One method in one class | `--filter='Full\\Namespace\\Class::method'` |
| Recurring multi-folder subset | Define `<testsuite>` in `phpunit.xml`, run `--testsuite=<name>` |
| Multiple raw file/folder paths at once | Not supported — always errors with `Too many arguments` |
