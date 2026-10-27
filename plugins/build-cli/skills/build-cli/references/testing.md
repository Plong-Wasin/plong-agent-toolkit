# Testing a CLI

Black-box tests with Node's built-in runner: no test dependency, and they exercise the file users actually run.

```
test/
  commands.test.ts        every command -> request sent (REST: method, path, query, body; MCP: tool and arguments)
  auth.test.ts            profiles, token sources, auth check (MCP: also OAuth login and refresh)
  helpers/fake-server.ts  a fake backend on a random loopback port
  helpers/cli.ts          runs dist/<bin>.js as a child process
```

`package.json`: `"test": "pnpm build && node --test \"test/*.test.ts\""`. Test files are TypeScript executed by Node's type stripping (Node 22.18+; CI uses 24). Use erasable syntax only (no enums, no parameter properties) and `.ts` extensions in imports. Add `tsconfig.test.json` extending the main one with `allowImportingTsExtensions` and `erasableSyntaxOnly`, and make `typecheck` run both.

## The fake server (`helpers/fake-server.ts`)

### REST fake (preferred transport)

One `http.createServer` on port 0:

- Records every request as `{ method, path, query (key -> string[]), body, token }` in `requests`, and answers 401 `{"detail":"Unauthorized"}` unless the bearer is in `validTokens`.
- Default fixtures per route, shaped like the OpenAPI schema (export small builders such as `issue(id)` and `event()` so tests can create variations). Unknown routes return `404 {"detail":"Not found."}`, so a typo in a CLI path fails loudly instead of passing.
- `reply(request)` override returns `{ status, body, headers }` or `undefined` to fall back to the defaults; it is how tests produce 403/404/429/400, a `Link` header for pagination, or a failure for one id in a bulk call.
- `reset()` between tests, `close()` at the end (`closeAllConnections()` so the run does not hang on keep-alive).

Reading `requests.at(-1)` after a run is the assertion for "the CLI sent exactly this". Prefer asserting the whole `query` object with `deepEqual` so an unexpected extra parameter is caught.

### MCP fake

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
- Each command: the exact request (REST) or tool name and arguments (MCP), defaults from the profile, flag over env over profile, `--json`, the table/summary output for one fixture, API error on stderr with exit 1 (401, 403, 404, 429, 400), unreachable server message (MCP also: SSE reply).
- REST pagination: a `Link` header produces the `--cursor` footer, `--cursor` is forwarded, `--all` follows every page and stops when the server says there are no more.
- Guarded writes: `--query` without `--yes` sends no write (assert no PUT/DELETE in `requests`) and exits 2; `delete` without `--yes` sends nothing; ids and `--query` together exit 2.
- Raw command: path normalisation, `key=value` to query, `--data` from argument and stdin, bad method, bad JSON, missing path.
- Id parsing: `123`, `#123`, URL accepted; `abc123`, `12abc`, `1.5`, empty rejected with exit 2 and no request sent.
- Bulk writes: one call per id (MCP: one session), a failure in the middle keeps going, is reported as `#id: ...`, and exits 1.
- Profiles: set from stdin and `--token`, `Bearer ` stripped, URL normalised, mode 600, masked status, use, logout moves the default, unknown profile lists the known ones.
- Credentials: `-p` and `<BIN>_PROFILE` selection, env token beats profile token, env URL + env token work with no profile, a profile without a token says how to add one, a rejected token is not retried.
- REST `auth check`: succeeds and lists what the token sees; a rejected token exits 1 with the hint.
- MCP only: OAuth refresh on 401 retries and saves rotated tokens, refused refresh asks to log in again; login with a pasted callback URL, loopback redirect, forged `state`, `error=access_denied`, re-login keeps URL and replaces a static token, missing `--url` exits 2.

## Rules

- MCP only: always pass `--manual` in login tests. Without it the CLI tries to open a real browser.
- Do not stub inside the CLI; extend the fake server instead, so tests keep covering the real transport.
- Run the whole suite twice after writing it; a flaky test usually means a missing wait on stderr or a shared port.
- Set `TMPDIR` somewhere disposable when an agent runs the tests.
- Before trusting a green run against a real service, remember what the fake cannot know: real response shapes and fields, the pagination header format, which token scopes writes need, and (MCP) session requirements and OAuth quirks. Say so when reporting, and have the user create a token or sign in once and try a read command to confirm.
