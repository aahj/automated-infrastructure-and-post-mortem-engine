# Repository Guidelines

## Project Structure & Module Organization

`main.py` exposes the FastAPI ingress and incident-approval endpoints; `worker.py` polls PostgreSQL and runs the LangGraph workflow. Core code lives under `src/`: graph state and routing are in `src/graph/`, agent nodes in `src/agents/`, database setup and ordered SQL migrations in `src/db/`, MCP integration in `src/_mcp/`, and Langfuse setup in `src/observability/`. Runtime data belongs in `data/`. Place automated tests in `tests/`, mirroring source modules (for example, `tests/test_workflow.py`).

## Build, Test, and Development Commands

Use Python 3.12 and a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env
```

Configure PostgreSQL, Ollama, and optional Langfuse/MCP services in `.env`, then run:

```powershell
python src/db/db.py       # apply SQL migrations in filename order
fastapi dev main.py       # start the API with reload
python worker.py          # start the queue-processing worker
black --check .           # verify formatting
isort --check-only .      # verify import ordering
```

There is currently no committed test suite or test runner dependency. When tests are added, use `pytest`, add it to `requirements-dev.txt`, and run `python -m pytest`.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation. Black is configured for 100-character lines and Python 3.12; isort uses Black-compatible ordering. Run `black .` and `isort .` before committing. Use `snake_case` for modules, functions, variables, and graph node names; `PascalCase` for classes and enums; and `UPPER_SNAKE_CASE` for constants. Keep asynchronous database, graph, and API operations as `async def` and avoid blocking calls in those paths.

## Testing Guidelines

Name files `test_<module>.py` and tests `test_<behavior>()`. Cover graph routing, state transitions, queue status changes, and error paths. Mock Ollama, PostgreSQL, MCP, and Langfuse at unit-test boundaries; reserve live-service checks for explicitly marked integration tests. Do not commit generated caches or coverage output.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commit prefixes such as `feat:` and `refactor:`; continue with concise, imperative subjects (for example, `fix: release stale queue locks`). Avoid `WIP` commits in review-ready branches. Pull requests should explain the behavior change, configuration or migration impact, and verification commands; link relevant issues and include sample requests/responses for API changes. Never commit `.env`, credentials, or production incident payloads.
