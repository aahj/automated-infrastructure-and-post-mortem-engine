# Owned Cross-Platform PM2 MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Restructure the repository into an app/ plus pm2-mcp/ monorepo, then replace the external PM2 MCP process with an owned, cross-platform server using PM2's programmatic API and per-request Bearer authorization.

**Architecture:** Move the existing Python application and its runtime configuration into app/. Add a standalone Node/TypeScript PM2 MCP server at repository-root pm2-mcp/. It calls PM2's programmatic API, serves stdio and direct HTTP Streamable HTTP, validates a static Bearer token on every request, and binds to 0.0.0.0:8486 for Docker access. Remove Caddy and its host-network mode completely.

**Tech Stack:** Node.js/TypeScript, official pm2 package/API, official MCP TypeScript SDK, Node built-in test runner, existing Python LangChain MCP adapter and httpx.

**Spec:** docs/superpowers/specs/2026-11-16-owned-pm2-mcp-server-design.md

## Global Constraints

- Do not invoke pm2, pm2.cmd, or user input through a shell.
- Use PM2's programmatic API and test on Windows and Linux with isolated PM2 homes.
- The HTTP server binds to 0.0.0.0:8486 by default; the host firewall must limit port 8486 to Docker client traffic.
- Require Authorization: Bearer <token> on every HTTP request. Use distinct configured read and write tokens; do not implement OAuth discovery or an authorization server.
- This static Bearer scheme is not the MCP OAuth 2.1 authorization flow; it is the requested private service-token scheme.
- The user explicitly chose plain HTTP. Bearer credentials are unencrypted, so the host firewall must limit port 8486 to Docker client traffic and the endpoint must not be exposed to a LAN or public network.
- Remove Caddy, its configuration, named volumes, and Docker host networking from the application deployment.
- start_service accepts only an allowlisted service definition; no arbitrary scripts or arguments.
- MCP session closure must not close the HTTP listener or PM2 API connection.
- Move tracked Python application assets into app/; keep .git, root AGENTS.md, and root .gitignore at repository root.
- Do not move the existing venv or generated caches; recreate the Python environment under app/ when needed.
- Do not run tests during implementation unless the user explicitly authorizes it; add tests and document commands.

## Review Focus

- PM2 API connect can launch a daemon: make behavior explicit and prevent accidentally targeting a new/default PM2 home.
- Binding to 0.0.0.0 exposes a host port: document and verify a restrictive host firewall rule.
- Missing or incorrect Bearer tokens must fail closed, and read tokens must never expose mutation tools.
- Plain HTTP makes the Bearer token observable to clients that can inspect traffic; ensure firewall guidance limits access to the Docker host path.
- Moving the Python app changes Compose paths, env-file lookup, Docker build contexts, and all test/documentation commands.
- HTTP client teardown must not stop the server or PM2 API connection; test two independent sessions.

---

### Task 1: Restructure the repository into app/ and pm2-mcp/

**Files and directories to move into app/:**
- .env and .env.example
- README.md, main.py, worker.py
- Dockerfile, docker-compose.yml, litellm-config.yaml
- requirements.txt, requirements-dev.txt, pyproject.toml
- src/, tests/, docs/, deploy/, docker/

**Repository-root items to retain or create:**
- Retain .git/, AGENTS.md, and .gitignore at root.
- Retain workspace-only .vscode/ and .superpowers/ at root.
- Do not move the existing venv/ or __pycache__; they are generated local state.
- Create root README.md with the two-project layout and links to app/README.md and pm2-mcp/.
- Create pm2-mcp/ for the new server package.

- [ ] Create app/ and move the listed Python application source, configuration, documentation, and local .env without printing or committing secret values.
- [ ] Update root .gitignore patterns for app/.env, app virtual environments, pm2-mcp/node_modules, build output, test caches, and local token files.
- [ ] Create a short root README.md that explains app/ and pm2-mcp/ and gives the correct working directories.
- [ ] Rewrite all Docker Compose commands to use app/docker-compose.yml and app/.env, with project directory app.
- [ ] Update Docker build contexts and bind-mount paths after relocation; preserve existing container behavior other than PM2/Caddy changes planned below.
- [ ] Review Git status and path references statically; do not run tests or containers.

### Task 2: Create the PM2 API client and cross-platform feasibility tests

**Files:**
- Create: pm2-mcp/package.json
- Create: pm2-mcp/package-lock.json
- Create: pm2-mcp/tsconfig.json
- Create: pm2-mcp/src/pm2-client.ts
- Test: pm2-mcp/test/pm2-client.test.ts
- Create: pm2-mcp/test/fixtures/fixture-process.js

**Interfaces:** Export Pm2Client with connect(): Promise<void>, listServices(): Promise<ServiceSummary[]>, getStatus(name: string): Promise<ServiceDetails>, startService(name: string): Promise<ServiceDetails>, stopService(name: string): Promise<ServiceDetails>, restartService(name: string): Promise<ServiceDetails>, reloadService(name: string): Promise<ServiceDetails>, and close(): Promise<void>. Hide callback-based PM2 APIs behind these promises.

- [ ] Add pinned Node/TypeScript dependencies and build/typecheck/test scripts using the Node built-in test runner.
- [ ] Define an injectable PM2 API interface and write unit tests for result normalization, exact method mapping, unknown targets, and PM2 errors.
- [ ] Add a fixture-process integration test using a temporary PM2_HOME; constrain setup and cleanup to that directory.
- [ ] Spike PM2 API connect behavior with and without an existing daemon on Windows and Linux; settle PM2_MCP_ALLOW_DAEMON_START before implementing startup.
- [ ] Implement the adapter without shell/process-spawn calls; keep one API connection for the server lifetime and close it exactly once.

### Task 3: Implement MCP tools and read/write Bearer authorization

**Files:**
- Create: pm2-mcp/src/tools.ts
- Create: pm2-mcp/src/auth.ts
- Test: pm2-mcp/test/tools.test.ts
- Test: pm2-mcp/test/auth.test.ts

**Interfaces:** Export registerPm2Tools(server, pm2Client, access) where access is read or write. Export authorizeRequest(request, config): AccessLevel and reject invalid tokens. Read access registers list_services and get_status. Write access registers those plus start_service, stop_service, restart_service, and reload_service.

- [ ] Define strict JSON input/output schemas and stable structured results for the tool contract.
- [ ] Write authorization tests for missing, invalid, read, and write tokens, including correct HTTP status handling.
- [ ] Implement constant-time comparisons for configured read/write tokens; never log or return token values.
- [ ] Enforce the read/write token mapping before MCP initialization and register only the corresponding tool set.
- [ ] Write input tests rejecting empty/wildcard/all targets, arbitrary command arguments, and start targets outside the configured allowlist.
- [ ] Implement tools through Pm2Client; keep errors actionable and redact secrets/environment data.

### Task 4: Implement direct HTTP Streamable HTTP and stdio servers

**Files:**
- Create: pm2-mcp/src/server.ts
- Create: pm2-mcp/src/config.ts
- Create: pm2-mcp/src/index.ts
- Test: pm2-mcp/test/http.test.ts
- Test: pm2-mcp/test/stdio.test.ts

**Interfaces:** loadConfig(env): ServerConfig; createServer(config, dependencies): Promise<RunningServer>; RunningServer.close(): Promise<void>. HTTP defaults to plain HTTP on 0.0.0.0:8486/mcp.

- [ ] Write HTTP lifecycle tests proving missing/invalid tokens get 401 and read/write tokens see the correct tool sets.
- [ ] Write repeated-session tests proving closing a client does not stop the listener or disconnect PM2.
- [ ] Implement native Node HTTP around the official MCP Streamable HTTP handler; do not add TLS or a reverse proxy.
- [ ] Support stdio mode with protocol-only stdout and stderr diagnostics; keep stdio read-only by default.
- [ ] Reject malformed token, bind, port, path, and PM2-home configuration at startup.
- [ ] Add graceful shutdown handling; close HTTP listener and PM2 API once, only on process shutdown.

### Task 5: Integrate direct Bearer authorization in the Python app and Compose

**Files:**
- Modify: app/src/_mcp/adapter.py
- Modify: app/tests/test_mcp_adapter.py
- Modify: app/tests/test_mcp_e2e.py
- Modify: app/docker-compose.yml
- Modify: app/.env.example
- Delete: app/deploy/Caddyfile.pm2-mcp

**Interfaces:** Investigator and engineer connections send the configured read token; executor sends the write token. Each request uses Authorization: Bearer <token>. The MCP URL is http://host.docker.internal:8486/mcp.

- [ ] Refactor PM2 MCP connection construction to use separate read/write Authorization headers per agent; retain existing client-side mutation filtering as defense in depth.
- [ ] Add adapter tests for exact Authorization header propagation and omission/rejection of missing token settings.
- [ ] Update the app's PM2 e2e setup to use the read token and direct HTTP.
- [ ] Remove pm2-mcp-proxy, Caddy Basic Auth variables, Caddy volumes, Caddy CA extraction, host-network mode, and all proxy dependencies.
- [ ] Configure worker/test containers with host.docker.internal:host-gateway and direct MCP URL; remove certificate mounts and SSL_CERT_FILE settings.
- [ ] Add read-only PM2 list/status e2e coverage and one authorized mutation test against an isolated PM2_HOME only.

### Task 6: Add cross-platform CI and operator documentation

**Files:**
- Create: .github/workflows/pm2-mcp.yml
- Modify: app/README.md
- Modify: root README.md

**Interfaces:** CI runs package build/unit/integration tests on windows-latest and ubuntu-latest. Operator docs specify read/write token setup, firewall restriction, server startup, and correct commands from app/ or pm2-mcp/.

- [ ] Add a Windows/Linux CI matrix with a pinned Node version compatible with PM2 and the MCP SDK.
- [ ] Use only temporary PM2_HOME and fixture processes in integration jobs; verify cleanup never targets the user's default PM2 state.
- [ ] Document that the server manages the PM2 daemon for its host user and PM2_HOME.
- [ ] Document static read/write Bearer token configuration, direct HTTP URL, token rotation by restart, and firewall restrictions for port 8486.
- [ ] Document Docker Desktop host.docker.internal usage; no Docker Desktop host-network setting or Caddy service is required.
- [ ] Document package unit/integration, app PM2 e2e, Compose PM2 e2e, and full e2e commands without executing tests.

### Task 7: Static review and handoff

**Files:** all moved and changed files

- [ ] Review PM2 API mapping, daemon-start policy, token validation, plain HTTP exposure, and firewall instructions.
- [ ] Review every moved path, Compose build context, env-file path, Python import path, and root README command.
- [ ] Run formatting, typecheck, or diff checks only if separately authorized; do not execute tests without user authorization.
- [ ] Report final repository layout, tests added but not run, static token requirements, and exact Windows/Linux/Compose commands.
