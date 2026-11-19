# Owned PM2 MCP Server

Node.js 20+ service that exposes PM2's programmatic API over MCP stdio or Streamable HTTP using
the MCP TypeScript SDK v2 and Fastify. HTTP
defaults to `http://0.0.0.0:8486/mcp` and requires distinct read/write Bearer tokens on every
request. The default listener is plaintext; restrict TCP 8486 with the host firewall to Docker
client traffic and never expose it to an untrusted network. These are static service Bearer tokens,
not OAuth access tokens; the server does not issue tokens or provide OAuth discovery.
The HTTP handler keeps stateless support for the 2025 MCP protocol used by the app's pinned Python
`mcp==1.28.1` client; SDK v2's modern protocol support is also available.

## Configure and start

Use [`.env.example`](.env.example) as the configuration template. The server loads `.env` from its
current working directory through `dotenv`; environment variables already set by the process take
precedence. For service managers or containers, injecting configuration through the runtime is also
supported.

Set `PM2_HOME` explicitly to the PM2 state directory to manage, and configure distinct random
`PM2_MCP_READ_TOKEN` and `PM2_MCP_WRITE_TOKEN` values (at least 32 characters each). By default,
PM2 runs in no-daemon mode if no existing daemon is available. Set
`PM2_MCP_ALLOW_DAEMON_START=true` to permit the server to create a persistent daemon.

```powershell
npm ci
$env:PM2_HOME = "$env:USERPROFILE\.pm2"
$env:PM2_MCP_READ_TOKEN = "<long-random-read-token>"
$env:PM2_MCP_WRITE_TOKEN = "<different-long-random-write-token>"
npm run build
npm start
```

Linux/macOS shells use the same variables with `export`. Set `PM2_MCP_TRANSPORT=stdio` to run
stdio mode; it is read-only unless `PM2_MCP_STDIO_ACCESS=write` is set. Console diagnostics are
written to stderr so stdio MCP protocol messages on stdout remain clean. Logs include lifecycle,
tool name, duration, and denial reason, but omit credentials and tool arguments. Optional
`PM2_MCP_START_TARGETS_JSON` maps approved service names to fixed `{ "script": "..." }`
definitions for `start_service`.
HTTP requests are also checked against `PM2_MCP_ALLOWED_HOSTS`, a comma-separated hostname list.
It defaults to `localhost,127.0.0.1,host.docker.internal`; add a hostname if clients connect using
another host name or IP. Requests with an Origin header must use the same hostname as the Host header.

## Tests

```powershell
npm ci
npm run build
npm run compile-tests
npm test
```

Set `RUN_PM2_INTEGRATION=1` to include the PM2 fixture lifecycle test. It creates and removes a
dedicated temporary `PM2_HOME`; it does not use the default PM2 state. Run package tests on Windows
and Linux. The app's direct HTTP e2e commands are documented in [`../app/README.md`](../app/README.md).
