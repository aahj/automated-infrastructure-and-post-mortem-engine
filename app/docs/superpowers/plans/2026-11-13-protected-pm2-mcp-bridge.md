# Protected PM2 MCP Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace the worker's PM2 MCP HTTP target with a loopback-only TadMSTR server protected for Docker access by a host-side TLS and Basic-auth Caddy proxy.

**Architecture:** Install the candidate on the host at reviewed commit `e30ab78f3d08f807d0ae6c0ddcc290144b987526` and run it at `127.0.0.1:8486` with `PM2_MCP_ENV_MODE=enforce`. Caddy runs as a Compose service with `network_mode: host`, listens on `8850`, authenticates clients, terminates TLS, and proxies `/mcp` to loopback. Compose worker/test clients remain on the regular Compose network, use `https://host.docker.internal:8850/mcp`, pass an Authorization header, and trust Caddy's root certificate. Docker Desktop requires host networking enabled (version 4.34+).

**Tech Stack:** Python 3.12 application, `langchain-mcp-adapters`, Docker Compose, external TadMSTR `pm2-mcp`, and host Caddy.

**Spec:** `docs/superpowers/specs/2026-11-13-protected-pm2-mcp-bridge-design.md`

## Global Constraints

- Keep the candidate MCP server bound to loopback; do not add a non-loopback bind override.
- Never commit proxy credentials or TLS private keys/certificates.
- Set the candidate host service to `PM2_MCP_ENV_MODE=enforce`.
- Expose PM2 mutating tools only to the mitigation executor, preserving the approval checkpoint.
- Run only Caddy with host networking; worker and test stay on the regular Compose network.
- Do not run tests; add the tests and provide commands for the user to run them.

## Review Focus

- An absent Authorization value must not silently become a configured shared credential; test that headers are omitted when unset.
- The upstream Host header must be loopback-compatible so the candidate's host/origin guard accepts Caddy's proxied request; pin this in the Caddy example and e2e instructions.
- A client session closing must not prevent a second initialization; add an e2e reconnection case.
- Compose must mount the CA read-only and point `SSL_CERT_FILE` at the mounted file; inspect both worker and test service configuration.
- Existing stdio adapter behavior must remain unchanged; retain its defaults and assertions.
- Read-only investigator and engineer tool lists must exclude all candidate write tools; executor keeps them.

---

### Task 1: Configure HTTP adapter credentials and URL

**Files:**
- Modify: `src/_mcp/adapter.py`
- Test: `tests/test_mcp_adapter.py`

**Interfaces:** HTTP mode consumes optional `PM2_MCP_URL` and `PM2_MCP_AUTHORIZATION`; it returns the MCP URL plus `headers.Authorization` when set. Without these values it preserves the existing URL construction and does not add headers.

- [x] Add tests for explicit HTTPS URL and Authorization header propagation, fallback URL construction, and omission of an unset Authorization value.
- [x] Add a test proving PM2 write tools are filtered for investigator/engineer and retained for the mitigation executor.
- [x] Update `_build_pm2_connection` to apply those settings only to HTTP transport while preserving stdio configuration.
- [x] Filter the candidate's `restart_service`, `stop_service`, `start_service`, `reload_service`, `save`, and `flush_logs` tools from non-executor agents in `get_tools`.
- [x] Review the focused adapter diff; do not execute tests.

### Task 2: Wire Compose services to the protected proxy

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:** Add a Caddy Compose service using `network_mode: host`; worker and test services use the proxy URL and authorization value, receive `SSL_CERT_FILE=/run/certs/pm2-mcp-root.crt`, and mount the operator-supplied CA path read-only. Worker/test stay on the project network.

- [x] Add example proxy URL, Authorization value, and ignored local CA path settings without adding actual secrets.
- [x] Set worker and test URLs to `https://host.docker.internal:8850/mcp` and pass the Authorization value into each service.
- [x] Add the Caddy service with host networking, persistent `/data` and `/config` volumes, and the example Caddyfile; do not add port publishing to a host-networked service.
- [x] Mount the configured CA path read-only in both services and set `SSL_CERT_FILE` to its container path.
- [x] Keep the existing `host.docker.internal` host-gateway mapping for the test service and add/confirm it for the worker.
- [x] Inspect rendered configuration structure statically; do not start containers.

### Task 3: Update PM2 MCP e2e coverage

**Files:**
- Modify: `tests/test_mcp_e2e.py`

**Interfaces:** Test setup maps `TEST_PM2_MCP_URL` and `TEST_PM2_MCP_AUTHORIZATION` into the adapter environment. PM2 e2e tests target the TadMSTR `list_services` and `get_status` tools.

- [x] Add a test that obtains tools, closes the first MCP session, obtains tools again through the same client, and confirms the expected tools remain available.
- [x] Change the process-list e2e test to invoke `list_services` and validate the returned JSON structure without requiring any mutating operation.
- [x] Require or clearly skip with missing names for PM2 URL/authorization configuration when HTTP mode is selected.
- [x] Review tests statically; do not execute them.

### Task 4: Document host setup and e2e execution

**Files:**
- Modify: `README.md`
- Create: `deploy/Caddyfile.pm2-mcp`
- Modify: `.gitignore` if needed for local proxy secrets/certificates

**Interfaces:** The Caddy example serves `host.docker.internal:8850` and `localhost:8850`, uses `tls internal` and `basic_auth`, proxies to `127.0.0.1:8486`, and rewrites the upstream Host header to `localhost:8486`.

- [x] Document installing TadMSTR `pm2-mcp` from the pinned commit in a host virtual environment and running it on loopback with `PM2_MCP_ENV_MODE=enforce` and the correct `PM2_HOME`.
- [x] Add the Caddy example with placeholders for the Basic-auth hash; explain how to copy Caddy's root CA into an ignored local path and trust it for host-local tests.
- [x] Document a host firewall rule that restricts TCP 8850 to the Docker/WSL source network; do not suggest unrestricted LAN exposure.
- [x] Document enabling Docker Desktop host networking (4.34+) and that only Caddy uses it; worker/test keep normal bridge networking.
- [x] Provide commands for the PM2-only host e2e test and the Compose test service, plus the full e2e suite command; state that live MySQL/Elasticsearch tests need their own disposable services and credentials.
- [x] State explicitly that the tests were added but not run.

### Task 5: Static review

**Files:** all changed files above

- [x] Review `git diff --check`, changed-file status, secret handling, Compose mount paths, adapter connection shape, and e2e assertions without running tests or containers.
- [x] Report the exact commands the user should run, and identify any host-specific Caddy/firewall setup value they must provide.
