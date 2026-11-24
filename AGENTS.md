# Repository Guidelines

## Project Structure & Module Organization

This repository contains two projects. `app/` is the Python incident-response service: API and worker entry points are at its root, application code is in `app/src/` (`agents/`, `graph/`, `db/`, and `_mcp/`), tests are in `app/tests/`, and Compose and Docker assets are alongside the application. `pm2-mcp/` is the TypeScript PM2 MCP server, with implementation in `src/` and Node tests and fixtures in `test/`. Each project has its own README and dependencies; run commands from that project's directory.

## Build, Test, and Development Commands

For the Python app, create a virtual environment, install `app/requirements.txt` and `app/requirements-dev.txt`, and configure `app/.env` from its example. From `app/`:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
black --check . && isort --check-only .
fastapi dev main.py
python worker.py
```

For PM2 MCP, use Node.js 20 or newer. From `pm2-mcp/`, run `npm ci`, `npm run build`, `npm run compile-tests`, and `npm test`. Set `RUN_PM2_INTEGRATION=1` to include its isolated PM2 lifecycle test. CI runs these checks on Windows and Ubuntu with Node 20 and 22.

## Coding Style & Naming Conventions

Python uses four-space indentation, Black with a 100-character line limit, and isort with Black-compatible ordering. Use `snake_case` for Python modules and functions and `PascalCase` for classes. TypeScript is compiled with the repository's `tsconfig.json`; follow existing typed module conventions and use descriptive lower-case filenames. Keep tests beside the relevant project test directory and name Python tests `test_<module>.py`.

## Testing Guidelines

Run Python unit tests with the command above; live MCP integration tests in `app/tests/e2e/` require their configured external services and should be run only in a suitable test environment. PM2 MCP tests use Node's built-in test runner; run `npm test` after compiling source and test TypeScript. Mock external services at unit boundaries and cover failure paths as well as successful behavior.

## Commit & Pull Request Guidelines

Recent commits mostly use Conventional Commit prefixes such as `feat:`, `fix:`, `refactor:`, and `chore:`. Keep subjects concise and action-oriented. Pull requests should describe behavior changes, list verification commands, call out configuration or migration changes, and link related issues. Include request/response examples for API changes. Never commit secrets, `.env` files, or real incident payloads.

## Security & Configuration

Use each project's `.env.example` for local configuration and keep credentials out of source control. The app can execute infrastructure mitigations after human approval, so use disposable systems and least-privilege credentials for development and integration tests. Restrict PM2 MCP access tokens and network exposure as described in `pm2-mcp/README.md`.
