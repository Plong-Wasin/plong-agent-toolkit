---
name: api-flow-prototype
disable-model-invocation: true
description: Build a single self-contained HTML file that lets someone click through a stateful UI flow AND see, live, exactly which API call (method + URL + JSON body) each action would trigger — with multiple named scenario buttons that auto-replay whole cases instead of requiring manual step-by-step clicking. Use this whenever the user wants to prototype or demo a UI flow together with its API contract, to align frontend and backend/API design — e.g. "อยากเห็นว่ากด save แล้วยิง API อะไรบ้าง", "ทำ prototype ที่มีหลาย case ให้ทีมดู flow", "สร้างหน้าตัวอย่างที่โชว์ endpoint ที่ยิง", "show me what this save button would actually call", or any request to visualize a CRUD/batch-save/state-machine contract as something clickable rather than just a written spec. Also trigger proactively when deep in an API design discussion and the user asks to "show" or "demo" the flow rather than just describe it in prose.
version: 1.2.0
---

# API Flow Prototype

A single `.html` file, opened by double-click or handed over as a scratch file, that makes an API contract *provable* instead of merely described. It has three parts working together: a pure state module (the actual logic, kept liftable into the real codebase), a translator from state changes into concrete `{method, url, body}` calls, and a page shell with a mock UI, an API panel, and a bank of scripted scenario buttons.

## When to reach for this vs. the general `prototype` skill

This is a specialized variant for one recurring situation: the user is designing (or has just finished designing) an API and wants to check the design by watching it play out as a UI. If the ask is purely "does this state machine feel right" with no API angle, or purely "what should this page look like" with no state logic to prove out, use the general `prototype` skill's `LOGIC.md` / `UI.md` instead. Reach for *this* skill specifically when both halves matter together — the UI's behavior and which network calls it produces.

## Step 1 — Nail down the interaction model before writing any code

The single most consequential decision is: **does every UI action fire its API call immediately, or does the UI defer everything into a local draft until some explicit "commit" action** (a Save button, a checkout button, a publish action)?

- **Immediate model** — each action's own panel just needs to show "this is what just fired." One append-only call log is enough.
- **Deferred model** — you need **two** panels: one showing what *would* fire if the commit action were pressed right now (recomputed live on every keystroke, styled visibly different — e.g. a dashed border — so it reads unmistakably as "not sent yet"), and one showing what's *actually* been sent (only ever populated by the commit action, append-only). This split is the entire point of the exercise under a deferred model — skip it and the prototype can't actually prove the claim "nothing happens until you click Save," which is usually the whole reason someone asked for one of these in the first place.

Ask, or infer from context, which model applies. Don't guess if it's ambiguous — it changes the whole shape of the panels and the diff function in Step 2.

## Step 2 — Design the diff/mapping function

This function *is* the API contract, made executable.

- **Immediate model:** write `describeCall(action, newState) -> {method, url, body}`. One call per action, no state comparison needed.
- **Deferred model:** write `computeDiff(savedState, draftState) -> {hasChanges, call}` — it compares two full states and returns the single request that would reconcile them (or `hasChanges: false`). If the domain has several sub-resources (attributes, line items, tags, whatever), express changes as separate explicit arrays per sub-resource — `things_create`, `things_update`, `things_delete` — rather than "send the whole current list and let the server infer what's missing." Inferring deletion from an item's *absence* is a classic silent-data-loss bug: a client that forgot to include one item on an unrelated edit permanently deletes it with no warning. Read `references/patterns.md` before implementing this function — it covers that failure mode plus two more that are easy to miss:
  - **Reordering must be its own array, decoupled from content updates.** If `_update` carries a `sort_order` field, dragging one item to the front makes every item between the old and new position look like it "changed," even though nothing about them did. A separate `_reorder` field (the full ordered list of current IDs) fixes this and is simple to validate (the ID set must match exactly).
  - **Referencing something created in the same request.** If a new line item needs to point at an attribute value that's *also* being created in this same batch, it doesn't have a real ID yet. Use a client-supplied temporary reference string (e.g. reuse the same local id the UI already uses, like `new-val-7`) instead of matching by name — matching by name silently fails the moment a name has a typo or gets renamed later.

Write this function **pure** — no `document`, no DOM, plain objects in and out — exactly like the state module. It's the second piece worth lifting into the real codebase once the design is validated.

## Step 2b — Model the response, not just the request

`describeCall`/`computeDiff` only prove half the contract: what the client sends. The other half — what the client gets back — is just as often the thing that turns into a bug later, because the frontend has to read specific field names off it, branch on its HTTP status, and know exactly what an error looks like when the server says no. A prototype that shows the request but leaves the response as an assumed "and then it just works" hasn't actually de-risked that half.

Write a second pure function, `describeResponse(action, resultingState, ok) -> {httpStatus, body}`, sitting right next to `describeCall`. Two outcomes matter:

- **Success body.** Whatever the real endpoint actually returns — mirror the real field names and wrapping (`{data: {...}}`, `{message, data}`, a bare object, whatever it really is) rather than inventing a shape that merely looks plausible. If you know the real backend (grep the codebase, ask the user, or check existing API docs) use its actual Resource/serializer fields; if you genuinely don't know, say so honestly in the "Not covered" note rather than guessing with confidence.
- **Rejection body.** Step 3 already asks for "an illegal action correctly blocked" among the scenarios — pair that scenario with the actual rejected response it would produce (status code plus error body), not just a toast saying "blocked." This is usually the more valuable half to get right: it's the case where the UI hid the button but a stale link, a race, or a bypassed client still reaches the server, and the server has to reject it on its own. Model that rejection as a real HTTP status + body, the same way you'd model the happy path.

Wire the result onto the same `firedHistory` entry as the request (`{...call, accepted, response}`), and show both **Request body** and **Response body** as two labeled sections in the fired-call detail view — not just the request repeated back. Use `response.httpStatus` to drive the call-log row's accepted/rejected styling (see `.call-row.rejected` / `.result-ok` / `.result-rejected` in the template) so a glance at the log already tells the difference between a call the server accepted and one it refused, before opening the row.

If the real response is large or only partly relevant (a full Order object when the flow only cares about three of its fields), abbreviate it and disclose the abbreviation in the "Not covered" note — exactly the same honesty policy the request side already follows for fields it deliberately left out.

## Step 3 — Build the page from the template

Copy `assets/template.html` and adapt it rather than writing the layout from scratch — it already has a working two-column layout (mock UI + side panels), full light/dark theme tokens matching the Artifact convention (explicit `data-theme` plus `prefers-color-scheme` fallback), a `.window`/`.chrome` mock browser frame (swap for a phone frame if the real UI is mobile-only), panel styles for the planned/fired split from Step 1, a scenario button bar with a runner that steps through a scripted list of actions, and a "Decision" section skeleton for Step 4.

Fill in: the domain's actual state shape, wire every control in the mock UI to the state module's `edit(action)` (deferred model) or `dispatch(action)` (immediate model) — never let a UI control fire a raw call directly, it always goes through the state module first — attach `describeResponse`'s result to every fired call per Step 2b, and write 4–7 named scenarios. Cover the happy path(s) plus whichever edge cases are genuinely hard to reason about on paper: an illegal action correctly blocked, two edits that cancel out before Save, a case that only shows up when editing something pre-existing rather than creating from scratch.

**Any text/number/date field wired to `oninput` needs the template's `captureFocus`/`restoreFocus` pair around its render function's `innerHTML` swap — this is already wired into `renderEditor()`, so it comes for free as long as you keep copying that function rather than writing a fresh one from scratch.** The reason it matters: `oninput` fires on every keystroke, and the render it triggers replaces the DOM wholesale, including the very `<input>` whoever's testing the prototype is mid-sentence typing into — without the capture/restore step, focus silently jumps out of the field after each character, so only the first keystroke ever lands and they have to click back in before every subsequent one. If the real domain needs a *second* live-editable container beyond `#editor` (e.g. a modal, a separate panel), copy the same capture-before/restore-after pattern around that container's `innerHTML` line too — it's not automatic just because the functions exist elsewhere on the page.

One extra wrinkle worth knowing about if you ever touch `restoreFocus` itself: `type="number"` and `type="date"` inputs throw when you read or set `selectionStart`/`selectionEnd` in Chrome (they don't support text selection), so the caret position can't be captured or restored the normal way. The template works around this by briefly swapping the input's `type` to `text` to place the caret, then swapping it back — skip that and the caret silently resets to position 0 on every render, which means typing "123" into an empty number field renders as "321" (each digit gets inserted at the front instead of appended). This is easy to miss because the field *looks* focused and functional right up until you type a second character.

## Step 4 — Write the rationale section

Below the interactive part, add a numbered "Decision" list — one item per real design choice actually embodied in the code, each with a short head and a body explaining the *why*, not just the what. This is often the most valuable part of the whole deliverable: it's the plain-language spec both frontend and backend can point at instead of re-deriving from the code. Close with a "note" callout for anything genuinely out of scope or still open (concurrency, partial-failure semantics, a guard that must also be re-checked server-side, etc.) — don't invent caveats that don't actually apply to what was built.

## Step 5 — Verify before handing it over

This is one big inline `<script>` — a typo silently breaks the whole page with no visible error in the artifact preview. Before calling it done, extract and syntax-check it:

```bash
python3 -c "
import re
html = open('PATH.html', encoding='utf-8').read()
m = re.search(r'<script>(.*)</script>', html, re.S)
open('_extracted.js', 'w', encoding='utf-8').write(m.group(1))
"
node --check _extracted.js && echo OK
rm _extracted.js
```

If the diff function or state module has any non-trivial logic (guard conditions, create/update/delete/reorder separation), also write a throwaway node test that exercises the pure functions directly — `node -e "..."` calling `buildBatchBody`/`computeDiff` with a couple of hand-built states and asserting on the result — before ever touching the browser. It's much faster to catch a logic bug this way (as opposed to clicking through by hand), and it catches a specific recurring mistake: chaining two scripted scenario steps that each re-read a stale array index (e.g. `items[2].id`) after an earlier step already changed the array — the second step silently grabs the wrong item and can cancel the first step out entirely. Re-resolve by a stable property (name, a fixed id) inside each step function instead of a snapshotted index.

## Output location and publishing

Default to just writing the `.html` file — put it in the scratchpad/working directory unless the user names a location. **Do not publish it as an Artifact unless the user explicitly asks.** If they do ask to publish, load the `artifact-design` skill first as usual, give it a title/favicon/description, and redeploy to the same URL on later revisions rather than creating a new artifact each time.

## Common mistakes to avoid

- Don't let the mock UI call `fetch()` or touch any real endpoint — everything is simulated in memory. The point is a safe space to check the *shape* of the contract, not a working integration.
- Don't skip the "planned" panel under a deferred-save model — that's the one thing that actually proves "nothing happens until you commit," rather than just asserting it in prose.
- Don't hardcode a single linear walkthrough — the value is in seeing several named cases side by side (happy path, an illegal action correctly blocked, an edge case that cancels out, editing something pre-existing vs. creating fresh), not one scripted story.
- Keep the state module and diff function pure. Reaching for `document` inside them is a sign the logic has leaked into the page and won't be liftable into the real codebase later.
- Don't write a new `oninput`-driven render function without the `captureFocus`/`restoreFocus` wrap around its `innerHTML` line (see Step 3) — otherwise every keystroke into that field kicks focus out, and the person testing the prototype can only ever type one character at a time.
- Don't stop at the request. A fired-call panel that only ever echoes the body back at you hasn't proven anything about the response — write `describeResponse` (Step 2b) and show it alongside the request, especially for whatever action gets server-rejected in your "illegal action blocked" scenario.
