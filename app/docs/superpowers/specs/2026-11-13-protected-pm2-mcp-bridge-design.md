# Protected PM2 MCP Bridge Design

## Intent

Let the Dockerized worker and e2e test container use PM2 tools on the host without relying on stdio or exposing an unauthenticated PM2 control endpoint. The current Node PM2 MCP HTTP process closes its listener when an MCP session closes; the TadMSTR server supports Streamable HTTP but refuses non-loopback binds.

## Chosen approach

Run TadMSTR `pm2-mcp` on host loopback, pinned to reviewed commit `e30ab78f3d08f807d0ae6c0ddcc290144b987526`. Run Caddy in a Docker container with `network_mode: host`; this lets Caddy reach the host's loopback PM2 server while preserving the candidate's bind restriction. Caddy provides TLS and Basic authentication, forwarding only `/mcp` to the loopback service. The Docker worker and test container stay on the ordinary Compose network, connect to Caddy using `host.docker.internal`, send the configured Authorization header, and trust Caddy's internal CA certificate. Restrict the proxy listener to trusted Docker traffic with the host firewall. Docker Desktop requires host networking to be enabled (version 4.34 or newer).

The candidate's `PM2_MCP_ENV_MODE=enforce` mode is required for the host service. PM2 MCP remains a privileged service: authenticated clients can stop, restart, reload, or flush logs for host PM2 services. The app exposes those mutating tools only to the mitigation executor, after its approval checkpoint. The proxy credentials and CA must not be committed.

## Alternatives considered

- Keep the current Node PM2 MCP over HTTP: rejected because its transport close handler shuts down the listening server after a client session closes.
- Bind TadMSTR `pm2-mcp` to a non-loopback address: rejected because it refuses that bind and has no built-in authentication; weakening that check would expose write tools.
- Use host loopback MCP behind a host-side authenticated TLS proxy: chosen because it preserves the candidate's loopback boundary and gives Docker a protected, reusable HTTP endpoint.

## Scope and constraints

- Extend the existing adapter to support an explicit PM2 MCP URL and Authorization header while retaining stdio configuration for non-Docker local use.
- Point Compose worker and e2e configuration at the HTTPS proxy and mount the Caddy CA certificate read-only.
- Update e2e assertions for the candidate tool names and verify a fresh MCP session can connect after the prior session closes.
- Document pinned host installation, loopback startup, Caddy configuration, CA trust, firewall restriction, and local/Compose e2e commands.
- Do not commit credentials or certificate material and do not run tests in this task.

## Acceptance

Adapter tests prove URL and header propagation. E2e tests target `list_services` and `get_status`, invoke the read-only service list, and reconnect with the same client. Run instructions distinguish host-local TLS trust from Compose CA mounting.
