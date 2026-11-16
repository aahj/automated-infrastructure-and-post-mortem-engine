# Owned Cross-Platform PM2 MCP Server Design

## Intent

Provide this application with a stable PM2 MCP server that works on Windows and Linux/WSL and can
serve Dockerized clients. The MCP server calls PM2's programmatic API; PM2 remains responsible for
starting and managing operating-system processes. This replaces the two external MCP servers whose
HTTP lifecycle and Windows command-launch behavior are unsuitable for this deployment.

## Goals

- Implement the bridge as a small, versioned Node.js/TypeScript package in this repository.
- Use PM2's programmatic API instead of spawning pm2, pm2.cmd, or an arbitrary shell command.
- Support stdio for local clients and Streamable HTTP for the Dockerized worker and e2e client.
- Keep the HTTP listener alive for the process lifetime. Closing an MCP session must not stop the
  listener or the PM2 connection.
- Bind HTTP to a Docker-reachable host interface, not loopback.
- Require a configured Bearer token in the Authorization header on every HTTP request, with separate
  read and write tokens mapped to the corresponding PM2 permissions.
- Expose read tools to investigator and engineer clients; expose write tools only to the executor
  credential, in addition to the application's approval checkpoint.
- Prove the PM2 API and MCP behavior on Windows and Linux with an isolated PM2_HOME.
- Move the existing Python application into app/ and add pm2-mcp/ as a sibling package at repo root.

## Non-goals

- Reimplement PM2, PM2's daemon protocol, or the PM2 command line.
- Change incident workflow behavior or remove the existing human approval checkpoint.
- Expose the PM2 HTTP listener to the public internet.
- Add arbitrary command execution or unrestricted script paths to MCP tools.

## Approaches considered

1. **Own Node/TypeScript bridge using PM2's programmatic API (chosen).** It uses PM2's documented
   connect, list, describe, and process action APIs, so it avoids Windows .cmd process spawning.
   The official MCP TypeScript SDK supplies stdio and Streamable HTTP transports. This keeps the
   bridge small and makes Windows/Linux integration testing direct.
2. **Own Python MCP server that launches the PM2 CLI (rejected).** Cross-platform command resolution
   would need separate Windows .cmd and POSIX behavior, recreating the exact class of issue already
   found in TadMSTR's server.
3. **Patch or fork one of the existing MCP servers — rejected.** It inherits an existing transport
   lifecycle defect or platform-specific subprocess behavior and leaves us maintaining upstream
   fixes in addition to our deployment.

## Architecture

The pm2-mcp package owns MCP tool schemas, authorization, and transport lifecycle. A small PM2
adapter wraps the official PM2 API behind a typed interface. The API connection is established for
the server process, reused for requests, and disconnected only during process shutdown. MCP client
session cleanup is independent of the listener and PM2 API lifecycle. Calls into the PM2 API are
serialized if API instance safety requires it.

The tool contract retains list_services, get_status, start_service, stop_service, restart_service,
and reload_service names for compatibility with the app's existing expectations. Read tools are
available to both credentials. Mutating operations require the write-scoped token; start_service
may target only a configured allowlisted service definition, never arbitrary shell arguments or a
user-supplied executable. save and flush_logs are deferred until their scope and value are confirmed
in implementation review.

HTTP uses the official MCP TypeScript SDK's Streamable HTTP transport on a persistent plaintext
HTTP listener bound to 0.0.0.0:8486 by default. Every HTTP request must include
Authorization: Bearer <configured-token>. The server compares the token against separately configured
read and write tokens and exposes tools allowed for that token. Tokens are static secrets rotated by
configuration and server restart; this is static Bearer authentication, not the MCP OAuth 2.1
authorization flow, and the server does not issue tokens. Stdio is
process-local and defaults to read-only unless explicitly configured. No Caddy, TLS, or reverse proxy
is part of the design.

The app's investigator/engineer MCP connections use the read token; the mitigation executor uses the
write token. Python connection configuration sends the appropriate static Authorization: Bearer
header on every request. Existing client-side tool filtering remains defense in depth. Worker and
test containers connect directly to http://host.docker.internal:8486/mcp. Since Bearer tokens are
unencrypted over HTTP, the host firewall must restrict port 8486 to Docker client traffic and the
endpoint must only be used on a trusted host network.

## Safety and failure behavior

- No MCP tool accepts a shell command, raw PM2 CLI argument list, or all as an implicit target.
- Mutating tools validate names against current PM2 records; start targets are checked against the
  configured allowlist.
- Each tool has bounded input and output schemas, returns structured data, and maps PM2 errors into
  actionable MCP errors without exposing secrets or environment values.
- The Authorization header is checked before MCP initialization and on every request. Missing or
  unknown tokens fail closed. The write token is never used for investigator or engineer connections.
- Plain HTTP exposes Bearer tokens to anyone able to observe traffic on the path. Restrict port 8486
  with the host firewall to Docker client traffic; do not expose it to a LAN or public network.
- Logs go to stderr for stdio mode; stdout contains only MCP protocol messages.
- If no PM2 daemon exists, the implementation must make startup behavior explicit. The PM2 API's
  documented connect can start a daemon, so the implementation spike must settle a safe
  PM2_MCP_ALLOW_DAEMON_START policy before tool work proceeds; it must not silently create a
  second/default PM2 instance.

## Validation strategy

Use mocked unit tests for tool schemas, authorization, input validation, error mapping, and API
method mapping. Use integration tests with a dedicated temporary PM2_HOME and a fixture process;
never use or kill the developer's default PM2 daemon. Cover Windows and Linux in CI. MCP protocol
tests cover stdio framing, Bearer-token authorization, tool lists for read/write tokens, and repeated
client sessions while the server remains available. The Compose e2e check connects directly to the
Node HTTP endpoint. Per the user's existing instruction, tests are to be added and commands
documented, but not run by the implementer without renewed authorization.

## References

- [PM2 programmatic API](https://pm2.keymetrics.io/docs/usage/pm2-api/)
- [PM2 official repository and supported platforms](https://github.com/Unitech/pm2)
- [MCP TypeScript SDK server and transport guidance](https://ts.sdk.modelcontextprotocol.io/server)
