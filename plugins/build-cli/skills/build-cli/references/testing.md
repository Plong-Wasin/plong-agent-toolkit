# Testing a CLI

Black-box tests with Node's built-in runner: no test dependency, and they exercise the file users actually run.

```
test/
  commands.test.ts        every command -> tool name and arguments sent
  auth.test.ts            profiles, credential precedence, OAuth login and refresh
  helpers/fake-server.ts  a fake backend on a random loopback port
  helpers/cli.ts          runs dist/<bin>.js as a child process
```

`package.json`: `"test": "pnpm build && node --test \"test/*.test.ts\""`. Test files are TypeScript executed by Node's type stripping (Node 22.18+; CI uses 24). Use erasable syntax only (no enums, no parameter properties) and `.ts` extensions in imports. Add `tsconfig.test.json` extending the main one with `allowImportingTsExtensions` and `erasableSyntaxOnly`, and make `typecheck` run both.

## The fake server (`helpers/fake-server.ts`)

One `http.createServer` on port 0 serving:

- `POST /mcp`: checks the bearer against `validTokens` (401 otherwise); `initialize` returns a `Mcp-Session-Id` and counts calls; other methods require that header; `tools/list`; `tools/call` records `{ name, arguments, token, sessionId }` in `calls` and returns a default `{ content: [text "ok:<name>"], structuredContent: { tool } }` unless `reply(name, args)` overrides it; an `sse` switch answers as an event stream.
- `GET /.well-known/oauth-authorization-server`, `POST /mcp/register` (records the body, returns a client id and secret), `GET /mcp/authorize` (plays the browser: stores the PKCE challenge, 302s to the redirect URI with `code` and `state`), `POST /mcp/token` (verifies the code verifier against the stored challenge, the redirect URI, client id and secret; handles `refresh_token` with rotation and records every request in `tokenRequests`).
- `reset()` between tests, `close()` at the end.

Because the fake verifies PKCE itself, a successful login test proves the CLI generated a correct verifier and challenge.

## The runner (`helpers/cli.ts`)

- `createCli()` makes a temp dir used as `HOME` and sets `<BIN>_CONFIG` to a file inside it, so the real `~/.config/<bin>` is never read or written. Pass only `PATH` plus those variables to the child so a developer's own `<BIN>_*` env cannot leak into the run.
- `run(args, { env, stdin })` resolves with `{ code, stdout, stderr }`; stdin is always closed so commands that read stdin do not hang.
- `start(args)` returns `{ stdin, waitForStderr(regex), done }` for interactive flows such as login.
- Helpers to write and read the config file and check its mode (`0o600`); a `cleanup()` for `after`.

## What to cover

- Top level: version, help without a profile, unknown command and unknown flag exit 2, dash-leading flag values, a flag missing its value still errors.
- Each command: the exact tool name and arguments, defaults from the profile, flag over env over profile, `--json` with and without `structuredContent`, tool error on stderr with exit 1, SSE reply, unreachable server message.
- Id parsing: `123`, `#123`, URL accepted; `abc123`, `12abc`, `1.5`, empty rejected with exit 2 and no request sent.
- Bulk writes: one call per id, one session, failure in the middle keeps going and exits 1.
- Profiles: set from stdin and `--token`, `Bearer ` stripped, URL normalised, mode 600, masked status, use, logout moves the default, unknown profile lists the known ones.
- Credentials: `-p` and `<BIN>_PROFILE` selection, env token beats profile token, rejected static token is not refreshed, OAuth refresh on 401 retries and saves rotated tokens, refused refresh asks to log in again.
- Login: pasted callback URL, loopback redirect, forged `state`, `error=access_denied`, re-login keeps URL and replaces a static token, missing `--url` exits 2.

## Rules

- Always pass `--manual` in login tests. Without it the CLI tries to open a real browser.
- Do not stub inside the CLI; extend the fake server instead, so tests keep covering the real transport.
- Run the whole suite twice after writing it; a flaky test usually means a missing wait on stderr or a shared port.
- Set `TMPDIR` somewhere disposable when an agent runs the tests.
- Before trusting a green run against a real service, remember what the fake cannot know: real response text, session requirements and OAuth quirks. Say so when reporting, and have the user sign in once to confirm.
