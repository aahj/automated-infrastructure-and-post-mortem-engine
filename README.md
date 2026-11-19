# Automated Infrastructure and Post-Mortem Engine

This repository contains two projects:

- [`app/`](app/README.md): the Python incident management application, Docker Compose configuration,
  and application tests. Run Python and Compose commands from `app/`.
- [`pm2-mcp/`](pm2-mcp/README.md): the owned cross-platform Node.js MCP server for PM2. Run npm
  commands from `pm2-mcp/`.

The PM2 MCP server uses PM2's programmatic API and serves authenticated Streamable HTTP for
Dockerized clients. See the app guide for host setup, token configuration, firewall restrictions,
and end-to-end test commands.
