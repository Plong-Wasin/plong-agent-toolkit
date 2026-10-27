# Layout and code patterns

The layout mirrors the user's MCP server projects (`src/index.ts`, `auth/`, a folder named after the backend, one file per domain, `utils/`) so they can navigate any of their repos the same way. Do not name a folder `mcp/` (the project is a CLI, not an MCP server) and do not use a catch-all `core/`.

## REST variant (preferred)

```
src/
  index.ts                  entry only: parse flags, dispatch, top-level error handling
  help.ts                   the --help text
  <backend>/client.ts       api(profile, method, path, {query, body}) -> {data, next}; list() follows cursors; error mapping
  <backend>/types.ts        response shapes copied from the OpenAPI schema
  <backend>/filters.ts      shared query-building, e.g. resolving a project slug to the id an endpoint wants
  commands/<area>-commands.ts   one file per area: issue, org, log, perf, auth ...
  commands/api-commands.ts  the raw `api <METHOD> <path>` escape hatch
  utils/config.ts           Config/Profile types, load/save (mode 600), resolveProfile (env-only profile too), maskToken
  utils/args.ts             requireArg, toInt, toId, parsePairs, requireOrg, defaults from env/profile
  utils/options.ts          the OPTIONS table and the derived Opts type
  utils/output.ts           printJson, printTable, printFields, pageFooter
  utils/format.ts           multi-line renderers (an issue, an event with stack frames)
  utils/errors.ts           CliError(message, exitCode)
  utils/version.ts          VERSION (JSON import)
test/                       see testing.md
```

No `auth/` folder: a bearer token needs no flow, so `auth set|check|use|logout|status` is just a command file.

## MCP variant

Same tree, but `<backend>/client.ts` is the MCP transport (session, bearer token, 401 refresh-and-retry, `callTool`), `<backend>/types.ts` holds ToolResult, ToolInfo and JSON-RPC types, `commands/raw-commands.ts` holds `info`, `tools` and `call`, `utils/output.ts` has `printToolResult`, `utils/version.ts` also exports `PROTOCOL_VERSION`, and there is an extra `auth/oauth.ts` (PKCE, loopback redirect, `--manual` paste, refresh).

Rules of thumb:

- A command file exports `cmdX(sub, rest, opts)` functions that resolve the profile, build the request, call the client (`api`/`list`, or `callTool`), and print. No transport or config code in them.
- `index.ts` stays a switch. If it grows logic, that logic belongs in a command or a util.
- A new area means a new `commands/<area>-commands.ts` and one `case` in `index.ts`, nothing else.
- Imports inside `src/` end in `.js` (NodeNext resolves them to the `.ts` files).

## Patterns worth copying

**REST client.** One `api()` function: build the URL (arrays repeat the query key: `project=1&project=2`; `undefined` values are dropped), send `Authorization: Bearer <token>` and `Accept: application/json`, parse JSON (an empty body is `undefined`, not an error), and map failures to `CliError`:

- 401 names the profile and URL and says to run `<bin> auth check`; 403 says the token may lack a scope for `METHOD path`; 404 and 429 (with `Retry-After`) have their own messages; any other status prints `HTTP <status> for METHOD path: <detail>`; a network failure says `Cannot reach <url>`.
- `detail` comes from the JSON body (`detail` or `message`), else the body text cut to a few hundred characters.

**Cursor pagination.** Return `{ data, next }`, where `next` is parsed from the `Link` header (`rel="next"` with `results="true"`, take `cursor="..."`). `list()` loops while `next` exists, up to a page cap (50). Verify the header format against the real server once: it was inferred from Sentry-style APIs in the reference CLI and not confirmed from the schema.

**Bulk by query.** Two paths in one command: per-id (`PUT /issues/{id}/` each) and query mode (one `PUT /organizations/{org}/issues/` with the filters as query parameters). Query mode first lists the matches and refuses without `--yes`.

**Raw command.** `api <METHOD> <path> [key=value ...] [--data JSON|@file|-] [--all]`: normalise the path to the API root (`/organizations/x/` and `/api/0/organizations/x/` both work), upper-case and validate the method, send `key=value` as query parameters, and print the JSON. This is also the way to try an endpoint before writing a shortcut for it.

**Errors.** Expected failures throw `CliError(message, exitCode)`; `main().catch` prints `<bin>: message` and exits with the code. `parseArgs` errors (`ERR_PARSE_ARGS_*`) exit 2. Anything else prints the stack and exits 1.

**Dropping unset arguments.** Build tool arguments as an object with `undefined` for flags the user did not pass and filter them before sending, so the server never sees `null` for an optional parameter.

**MCP over HTTP.** POST `<base>/mcp` with `Authorization: Bearer`, `Accept: application/json, text/event-stream`, `MCP-Protocol-Version`. Send `initialize` once per process, keep the `Mcp-Session-Id` response header and send it afterwards, then `notifications/initialized` (a notification has no `id`; expect 202). Responses may be JSON or an SSE stream; for SSE take the `data:` line that holds the `result` or `error`.

**401 handling.** If the profile uses OAuth and the first request returns 401, refresh the access token once, save the new tokens (rotating refresh token included) to the config, retry. A static token or an env token is never refreshed; the error says "Check the token". The message names the profile and URL.

**Credential precedence.** Env token, then the profile's static token, then its OAuth access token.

**Profiles.** REST: `{ defaultProfile, profiles: { name: { url, token, org?, project?, environment? } } }`; `auth set <name> --url ...` takes the token from `--token` or stdin (a leading `Bearer ` stripped), `auth check` calls a cheap list endpoint to prove the URL and token work and prints what the token can see, `auth login` exists only to explain that browser login was removed. MCP: `{ ..., oauth? }`. `auth login <name> --url ...` stores OAuth state and clears any static token; `auth set <name> --url ...` (token from `--token` or stdin, a leading `Bearer ` stripped) stores a static token and clears OAuth state. First profile becomes the default. `auth status` marks the default with `*`, shows `oauth` or `token` and only the last four characters. The base URL is stored without a trailing slash or `/mcp`.

**OAuth login.** Discover `/.well-known/oauth-authorization-server`, register a client dynamically with a loopback redirect, open the authorize URL with a PKCE S256 challenge and a random `state`, wait for the redirect on `127.0.0.1:<random port>/callback` or (with `--manual`) a pasted URL, whichever comes first, verify `state`, exchange the code with the verifier. Always print the URL as well as trying to open it.

**Dash-leading values.**

```ts
// parseArgs reads `--sort -count` as two flags. Glue a dash-leading value to the
// string option before it unless it is itself a known flag.
function glueDashValues(argv: string[]): string[] { /* long string options only */ }
parseArgs({ args: glueDashValues(process.argv.slice(2)), allowPositionals: true, options: OPTIONS });
```

Only long options can take `=value`, so short flags are left alone.

**Version.**

```ts
import pkg from '../../package.json' with { type: 'json' };
export const VERSION: string = pkg.version;
```

This needs `resolveJsonModule: true` in tsconfig, and the bundler inlines the JSON.
