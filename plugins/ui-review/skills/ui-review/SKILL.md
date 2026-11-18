---
name: ui-review
description: Review a UI change by looking at rendered screenshots, not code. Use when a diff touches screens, components, styles or UI copy (web or mobile app), before opening a PR, and on /ui-review. A fresh agent with no context critiques every changed screen and state at phone and desktop size in each shipped language, returns findings ordered by severity, and the author fixes and recaptures.
---

# UI review

Judge the change as a user sees it. Rendered pixels are the evidence; markup and diffs are not.

## Steps

1. **Scope.** List every screen and state the diff changes: default, empty, error, loading, long text, destructive dialog, offline or disabled. Done when each has a name. A diff with no UI change ends here with "no UI change".
2. **Capture.** Use the repo's own capture path first (its agent docs, repo profile, visual or e2e tooling). With none, render with Playwright or a headless browser for web, an emulator or golden test for mobile. Sizes: phone and desktop for web, smallest and largest supported device for mobile. Languages: every one the UI ships, the longest-text language included (Thai or German before English). Seed realistic data: names, counts and strings as long as production's. Done when every state from step 1 has one screenshot per size and language, saved under the repo's git-ignored scratch folder (`.local/` or the scratchpad).
3. **Critique.** Launch a fresh read-only general-purpose Agent. Give it the screenshot paths, a one-sentence goal of the change, and the changed files. It looks at each image with the image reader, and runs `impeccable critique` when that skill is installed, so design rules stay in one place. It checks:
   - hierarchy: the primary action and the main fact are the first things seen
   - fit: no clipped, overlapping or wrapped-awkwardly text; nothing overflows sideways
   - destructive actions: named target, stated consequence, a visible difference from safe actions
   - states: empty, error and long-text cases read clearly
   - reach: touch targets 44 px or larger, focus visible and returned to the trigger after a dialog, contrast readable
   - consistency: matches neighbouring screens' spacing, wording and controls
4. **Report.** One finding per item: severity (blocker, major, nit), the screenshot path, what is wrong, what to change. Close with a verdict: `ship` / `fix-then-ship` / `rework`.
5. **Fix and recapture.** The author fixes every blocker and major, recaptures the affected states, and repeats from step 3 with a fresh Agent. At most 3 rounds; unresolved findings go in the report.
6. **Hand over.** Give the user the absolute screenshot paths and the verdict. Taste is the user's call: never mark the work approved on their behalf.

## Rules

- A finding cites a screenshot. A claim from reading code alone is labelled _inferred_.
- Refinement keeps the existing design language and strings; a finding that asks for a redesign says so.
- Screenshots stay out of git.
