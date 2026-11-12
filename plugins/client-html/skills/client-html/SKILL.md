---
name: client-html
description: "Create or revise standalone HTML documents for clients, including proposals, workflow explanations, and option comparisons with readable diagrams. Use for requests such as ทำ HTML ส่งลูกค้า or เอกสารให้ลูกค้าดู; not for building application screens."
---

# Client HTML

Produce an HTML file the user can share with a client without having to explain the engineering conversation behind it. Match the audience's language; for Thai clients, use natural Thai and explain unavoidable technical terms at first use.

## Establish the content

- Use the conversation to identify the reader, requested outcome, current behavior, proposed changes, constraints, and decisions still needed. Ask only for missing information that materially changes the deliverable.
- Distinguish current implementation, intended business rules, and proposed behavior. If reviewing code, trace the values used in the relevant calculation or decision, not merely function order. Executing a discount step first does not prove later checks use the discounted amount. A discovered bug describes implementation, not necessarily the agreed requirement.
- Fix the reader before writing: the default reader is a non-technical client or PM; the user may name a developer instead. Keep that choice for the whole document.
  - Non-technical reader (default): no field names, column values, code identifiers, or system jargon (write "not published", not `publish_status = 0`). Build most of the content from tables and diagrams, with at most a short paragraph around each. Every number traces to a query result or file from this session.
  - Developer reader: field names, ids, and code paths are welcome. Keep the tables and diagrams so the page stays quick to read.
- Keep evidence and code paths in the user-facing handoff when useful; keep internal debugging details out of the client artifact unless requested. Qualify claims that were inspected but not executed.
- When minimal code change is a stated priority, recommend reusing existing behavior where it meets the requirement. Explain the remaining necessary work without inventing schedules, costs, or guarantees.

## Explain the decision

Lead with what the client gains and the proposed approach. Add only sections that help that reader decide: current versus proposed flow, a concrete numerical example, relevant benefits and drawbacks, stakeholder effects, and unresolved business choices.

- Compare options on the same dimensions. Include the current approach when useful, and make any unmet requirement explicit. Keep alternatives proportional to the requested scope.
- Consider the relevant buyer, seller, administrator, or operator perspectives. State what the change means to each rather than automatically designing new screens or reports.
- Label units precisely: a usage count, customer count, order count, shipment count, and monetary total may differ. State example assumptions and reconcile totals and rounding.
- Identify a topic introduced by the team as a proposal, rather than implying the client requested or approved it. Include questions only where a real decision remains; settled points should read as settled.

## Build a portable document

- Default to one standalone HTML file with UTF-8, a viewport declaration, inline CSS, and system fonts with suitable Thai fallback. Keep content and diagrams usable offline. Use HTML/CSS or inline SVG for simple flows; avoid a CDN renderer required to see the diagram.
- Give diagrams enough space to read labels comfortably. Prefer full-width current/proposed diagrams stacked vertically for detailed comparisons; use side-by-side layouts only when labels remain readable. Include visible flow direction, captions, and text labels so color is not the only cue.
- Use restrained styling, comfortable line height, responsive layout, and print CSS. Let wide tables wrap or scroll on small screens; avoid shrinking all content to fit. Print output should preserve content without clipping long sections.
- Use the requested output path. When none is given, a descriptive filename in `/tmp` is a reasonable draft location. Copy to another location when requested and identify the delivered file clearly. Preparing the artifact does not authorize sending it to a client.

## Revise and finish

For existing documents, edit the latest agreed file and preserve accepted content. Apply requested deletions precisely, then repair orphaned references, numbering, table structure, or conclusions that depended on the removed text. Honor excluded topics across the document without turning those exclusions into permanent rules for unrelated future documents.

Before delivery, check HTML structure, navigation targets, example arithmetic, current/proposed labels, and consistency with the latest user edits. Check that diagrams and assets have no unintended network dependency.

A page with a diagram is done when you have looked at a rendered screenshot of it, at desktop and phone width, and confirmed every label sits inside its box, no text overlaps, and every arrow reaches its target. Parsing the markup or checking the arithmetic does not show this; clipped or overflowing text only appears when rendered.

Render with whatever the session offers, in this order: a browser skill or MCP (Playwright, Orca browser), then a headless browser on the host (`chromium --headless --screenshot`, `google-chrome --headless --screenshot`). Open the screenshot with the image reader. With no renderer at all, say plainly in the handoff that the diagram was not viewed, and ask the user to check it before it goes to the client. Keep diagram box sizes derived from their content (rows × row height) so a static review can still catch a mismatch.

Return a clickable link to the finished file and a short description of the material change. If copying the final artifact, verify that the delivered copy matches the source.
