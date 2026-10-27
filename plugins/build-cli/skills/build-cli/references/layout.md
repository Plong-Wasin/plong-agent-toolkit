# Layout and code patterns

The layout mirrors the user's MCP server projects (`src/index.ts`, `auth/`, a folder named after the backend, one file per domain, `utils/`) so they can navigate any of their repos the same way. Do not name a folder `mcp/` (the project is a CLI, not an MCP server) and do not use a catch-all `core/`.

```
src/
  index.ts                  entry only: parse flags, dispatch, top-level error handling
  help.ts                   the --help text
  auth/oauth.ts             OAuth login (PKCE, loopback redirect, --manual paste) and refresh
  <backend>/client.ts       transport: session, bearer token, 401 refresh-and-retry, callTool
  <backend>/types.ts        ToolResult, ToolInfo, JSON-RPC message types
  commands/<area>-commands.ts   one file per area: issue, org, log, perf, raw, auth ...
  utils/config.ts           Config/Profile types, load/save (mode 600), resolveProfile, maskToken
  utils/args.ts             requireArg, toInt, toId, parseKeyValues, requireOrg, defaults from env/profile
  utils/options.ts          the OPTIONS table and the derived Opts type
  utils/output.ts           printToolResult, printJson
  utils/errors.ts           CliError(message, exitCode)
  utils/version.ts          VERSION (JSON import), PROTOCOL_VERSION
test/                       see testing.md
```

Rules of thumb:

- A command file exports `cmdX(sub, rest, opts)` functions that resolve the profile, build the arguments, call `callTool`, and print. No transport or config code in them.
- `index.ts` stays a switch. If it grows logic, that logic belongs in a command or a util.
- A new area means a new `commands/<area>-commands.ts` and one `case` in `index.ts`, nothing else.
- Imports inside `src/` end in `.js` (NodeNext resolves them to the `.ts` files).

## Patterns worth copying

**Errors.** Expected failures throw `CliError(message, exitCode)`; `main().catch` prints `<bin>: message` and exits with the code. `parseArgs` errors (`ERR_PARSE_ARGS_*`) exit 2. Anything else prints the stack and exits 1.

**Dropping unset arguments.** Build tool arguments as an object with `undefined` for flags the user did not pass and filter them before sending, so the server never sees `null` for an optional parameter.

**MCP over HTTP.** POST `<base>/mcp` with `Authorization: Bearer`, `Accept: application/json, text/event-stream`, `MCP-Protocol-Version`. Send `initialize` once per process, keep the `Mcp-Session-Id` response header and send it afterwards, then `notifications/initialized` (a notification has no `id`; expect 202). Responses may be JSON or an SSE stream; for SSE take the `data:` line that holds the `result` or `error`.

**401 handling.** If the profile uses OAuth and the first request returns 401, refresh the access token once, save the new tokens (rotating refresh token included) to the config, retry. A static token or an env token is never refreshed; the error says "Check the token". The message names the profile and URL.

**Credential precedence.** Env token, then the profile's static token, then its OAuth access token.

**Profiles.** `{ defaultProfile, profiles: { name: { url, token?, oauth?, org?, project?, environment? } } }`. `auth login <name> --url ...` stores OAuth state and clears any static token; `auth set <name> --url ...` (token from `--token` or stdin, a leading `Bearer ` stripped) stores a static token and clears OAuth state. First profile becomes the default. `auth status` marks the default with `*`, shows `oauth` or `token` and only the last four characters. The base URL is stored without a trailing slash or `/mcp`.

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
