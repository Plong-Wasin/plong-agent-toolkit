# Diff engine patterns

Deeper notes for Step 2 of the main skill. Read this before writing `computeDiff`/`buildBatchBody` for a deferred-save model, or `describeCall` for an immediate one.

## 1. Never infer deletion from absence

The most common mistake in a first draft: representing a sub-resource list by just sending the client's current full array and letting the server diff it against what's stored.

```json
// BAD — declarative full-state
{ "variants": [ { "id": "var-1", "price": 199 } ] }
```

If the client's array is missing an item that exists on the server for *any* reason — a pagination bug, a stale cache, a field the UI simply doesn't render — the server has no way to distinguish "the seller deleted this on purpose" from "the client just didn't happen to send it this time." The safe shape makes deletion its own explicit list:

```json
// GOOD — explicit diff arrays
{
  "variants_create": [ { "price": 199, "stock_quantity": 20 } ],
  "variants_update": [ { "id": "var-1", "price": 210 } ],
  "variants_delete": [ "var-2" ]
}
```

Now a variant only disappears because its id showed up in `variants_delete` — never because it was merely absent from a list.

## 2. Decouple reorder from update

Once delete is its own array, a second, subtler version of the same mistake shows up: cramming a computed `sort_order` into the `_update` array.

```json
// BAD — one drag touches everything between old and new position
{ "values_update": [
  { "id": "val-1", "sort_order": 0 },
  { "id": "val-2", "sort_order": 1 },
  { "id": "val-3", "sort_order": 2 }
] }
```

If the seller only dragged `val-3` from last to first, `val-1` and `val-2` didn't change at all — but they show up in `_update` anyway because their *index* shifted. This makes diffs noisy and makes it look like content changed when only position did. Give order its own field, as a full explicit list of current IDs (never partial):

```json
{
  "values_reorder": [
    { "attribute_id": "attr-30", "value_ids": ["val-3", "val-1", "val-2"] }
  ],
  "values_update": []
}
```

Validate by checking the ID *set* matches exactly what should exist after create/delete are applied — not by trusting an implicit "whatever's missing must not have moved."

This generalizes to any resource with a stable order: attributes themselves, values within an attribute, images on a product, steps in a sequence. Three orthogonal questions, three fields: does it exist (`_create`/`_delete`), did its content change (`_update`), did its position change (`_reorder`).

## 3. Referencing something created in the same request

A one-shot atomic batch can't sequence "create A, get its real id back, then create B referencing A's id" the way a chain of separate REST calls could — there's no round-trip in between. Two fixes, prefer the first:

- **Client-supplied temporary reference.** Reuse whatever local/temp id the UI already assigned when the item was created in the draft (e.g. `new-val-7`), send it in a `client_ref` field alongside the real create payload, and let the thing referencing it (e.g. `variants_create[].attribute_value_ids`) include that same string. The server resolves `client_ref -> real id` within its own transaction before it needs the reference, then returns the mapping (or the full fresh resource) in its response so the client can swap its local temp ids for real ones.
- **What NOT to do:** match by name (`{"attribute": "Size", "value": "XL"}`) instead of id. It looks convenient but fails silently the moment there's a typo, a case-sensitivity mismatch, or someone renames the thing later — and there's no error, just a reference that quietly doesn't attach to anything.

## 4. The scenario stale-index trap

When scripting a scenario as a list of action-producing functions `(state) => action`, each function receives the state *as of that step* — which already reflects every earlier step's mutation. A step that does:

```js
(s) => ({ type: 'MOVE_VALUE', valueId: s.attributes[0].values[2].id, direction: 'up' })
```

twice in a row, intending "move the same item up twice," actually moves whatever item *now* sits at index 2 — which, after the first move, is a *different* item than before. Two moves that were meant to compound can silently cancel each other out, and the resulting diff shows zero changes with no obvious explanation why.

Fix: resolve the target by something stable across the whole scenario, not a snapshotted index —

```js
(s) => ({ type: 'MOVE_VALUE', valueId: s.attributes[0].values.find(v => v.name === 'L').id, direction: 'up' })
```

Always sanity-check a multi-step scenario against the pure state module directly (`node -e`) before trusting what the browser shows — it's much faster to spot a cancelling-out sequence this way than by eyeballing the rendered UI.
