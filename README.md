# Automated Infrastructure and Post-Mortem Engine

An AI-assisted incident-response service that accepts monitoring alerts, investigates them with
local language models and infrastructure tools, pauses for a human decision, and executes only
approved mitigation steps. FastAPI provides the ingress and approval API, PostgreSQL provides both
the durable work queue and LangGraph checkpoints, and a separate worker runs the incident workflow.

The project is designed to shorten the slow, repetitive part of incident response without removing
human control from potentially destructive actions. It turns unstructured alert payloads into a
consistent incident state, gathers evidence through MCP tools, proposes a mitigation, records an
approval decision, executes the approved plan, and verifies recovery with read-only checks.

> [!IMPORTANT]
> This is an experimental operations tool, not a replacement for production change controls.
> Review the MCP tools and their credentials, restrict their permissions, and test every mitigation
> in a non-production environment before granting access to live infrastructure.

## What problem it solves

Incident response often requires an operator to correlate a noisy alert with application logs and
database state, decide on a safe action, perform it, and then prove that the service recovered. That
process is time-sensitive, difficult to standardize, and prone to losing context between tools and
people. This engine provides one durable workflow for those steps:

- normalizes arbitrary webhook payloads into a structured incident record;
- uses tool-calling agents to gather evidence and identify a likely root cause;
- persists graph state so an incident can safely pause for human approval;
- separates read-only investigation and verification from mutation-capable execution;
- resumes approved or rejected incidents through a PostgreSQL-backed queue; and
- optionally sends LangGraph and model traces to Langfuse.

## Current implementation status

The checked-in workflow implements alert ingestion, triage, MCP-assisted investigation, a human
approval interrupt, approved mitigation execution, and read-only recovery verification. The
post-mortem scribe and external A2A/CrewAI handoff shown in the architecture diagrams are planned but
are currently commented out in `src/graph/workflow.py`; a successfully verified incident presently
ends the graph. The diagrams below are retained as the project workflow and target architecture.

## Contents

- [Workflow](#the-langgraph-flow)
- [System architecture](#the-complete-system-architecture)
- [How the system works](#how-the-system-works)
- [Technology stack](#technology-stack)
- [Local development](#local-development)
- [API reference](#api-reference)
- [Deployment](#deployment)
- [Testing and code quality](#testing-and-code-quality)
- [Operations and troubleshooting](#operations-and-troubleshooting)

---

## The LangGraph Flow
```mermaid
graph TD
    %% Nodes
    START([START]) --> triage_commander[triage_commander<br>#40;Triage Commander#41;]
    
    triage_commander --> log_investigator[log_investigator<br>#40;Log & Metrics Investigator - ReAct Tool Loop#41;]
    
    log_investigator --> human_approval{human_approval<br>#40;Human Approval Gate#41;}


    mitigation_executor[mitigation_executor<br>#40;Mitigation Executor - reAct Tool Loop#41;]
    
    mitigation_engineer[mitigation_engineer<br>#40;Mitigation Engineer#41;]
    post_mortem_scribe[post_mortem_scribe<br>#40;Post-Mortem Scribe via A2A#41;]
    
    END([END])

    %% Edge Transitions
    human_approval -.->|approved = true| mitigation_executor
    human_approval -.->|approved = false / rejected| END
    
    mitigation_engineer -.->|is_resolved = false / retry| log_investigator
    mitigation_engineer -.->|is_resolved = true| post_mortem_scribe
    
    mitigation_executor -.->|Execution| mitigation_engineer
    
    post_mortem_scribe --> END

    %% Styling
    classDef default fill:#1f2937,stroke:#4b5563,stroke-width:2px,color:#f9fafb;
    classDef startEnd fill:#10b981,stroke:#059669,stroke-width:2px,color:#fff;
    classDef conditional fill:#f59e0b,stroke:#d97706,stroke-width:2px,color:#fff;
    
    class START,END startEnd;
    class human_approval conditional;
```

---
## The Complete System Architecture

```mermaid
graph TB
    %% External Telemetry Sources & Ingress Gateway
    subgraph INGRESS [INGRESS & QUEUE LAYER]
        PROM[Prometheus / Grafana Alert] -->|HTTP POST Webhook| API[FastAPI Gateway]
        CW[AWS CloudWatch Alert] -->|HTTP POST Webhook| API
        PD[PagerDuty Webhook] -->|HTTP POST Webhook| API
        
        API -->|1. Inserts 'pending' job| QUEUE[(PostgreSQL Alert Queue)]
        WORKER[Background Worker / Runner] -->|2. Polls & Claims Job| QUEUE
    end

    %% Orchestration Layer (LangGraph Stateful Workflow)
    subgraph ORCH [ORCHESTRATION LAYER - LangGraph Stateful Workflow]
        direction TB
        
        %% Entry Node
        TP[triage_commander<br/>#40;Triage Commander#41;]
        
%% Core Diagnostic Node
        LI[log_investigator<br/>#40;Log & Metrics Investigator - Tool ReAct Loop#41;]

        %% Stateful Intercept
        HA{human_approval<br/>#40;Human Approval Gate#41;}
        
        %% Mitigation Executor Node
        ME_EX[mitigation_executor<br/>#40;Mitigation Executor - reAct Tool Loop#41;]
        
        %% Core Action & Report Nodes
        ME[mitigation_engineer<br/>#40;Mitigation Engineer#41;]
        PMS[post_mortem_scribe<br/>#40;Post-Mortem Scribe#41;]
        
        %% Flow Connections
        TP --> LI
        LI -->|Raw Tool Outputs| HA
        HA -->|Approved / Execute Plan| ME_EX
        HA -->|Rejected / False Alarm| END_NODE([END])
        
        ME -->|Resolved| PMS
        ME -->|Failed / Needs More Data| LI
        ME_EX -->|Execution Plan| ME
        PMS --> END_NODE
        
        %% Checkpoint Storage 
        DB[(PostgreSQL<br/>Async Checkpoint Store)] <--->|Persists State Per Node Execution| TP & LI & HA & ME & PMS
    end

    %% Worker triggers graph execution
    WORKER -->|3. graph.ainvoke#40;raw_alert_payload#41;| TP

    %% Observability & Quality Layer
    subgraph OBS [OBSERVABILITY & QUALITY LAYER]
        LF[Langfuse<br/>#40;Distributed Tracing#41;]
        DE[DeepEval<br/>#40;Automated Quality Checks / LLM-as-a-Judge#41;]
    end

    %% Connect Orchestrator to Observability Callbacks
    ORCH -.->|Emits Traces| LF
    ME -.->|Validates Metrics via| DE
    PMS -.->|Evaluates Report Tone via| DE

    %% Decentralized Tool Layer (Model Context Protocol)
    subgraph TOOL [TOOL LAYER - Multi-Source MCP Servers]
        direction LR
        LOKI_MCP[Loki/Elastic MCP Server<br/>#40;App Containers Logs & Metrics#41;]
        DB_MCP[PostgreSQL MCP Server<br/>#40;DB Metrics, Locks, & Slow Queries#41;]
        MEM_MCP[MCP Memory Server<br/>#40;Historical Incident Context#41;]
    end

    %% Agent-to-Tool mappings
    LI ===>|1. Checks App Container Logs| LOKI_MCP
    LI ===>|2. Cross-References DB State| DB_MCP
    ME ===>|Reads/Writes Action History| MEM_MCP

    %% Inference Layer (Ollama)
    subgraph INF [INFERENCE LAYER - Ollama Local Host:11434]
        LLM[qwen2.5 / qwen2.5-coder Models]
    end

    %% All LLM Nodes query Ollama
    TP & LI & ME & PMS ---->|Local Inference Fan-In| LLM

    %% External Delegation Layer (Agent-to-Agent Protocol)
    subgraph A2A [A2A LAYER - Cross-Framework Protocol]
        direction TB
        PMS_SVC[Post-Mortem Scribe A2A Service<br/>#40;Port 9001#41;]
        CREW_AGNT[CrewAI Document Specialist<br/>#40;Port 9002#41;]
        PMS_SVC ===>|JSON-RPC 2.0 Handoff| CREW_AGNT
    end

    %% Graph Delegation Route
    PMS ===>|Delegates Document Generation| PMS_SVC

    %% Global Styling
    classDef default fill:#1e1e2e,stroke:#45475a,stroke-width:2px,color:#cdd6f4;
    classDef layer fill:#313244,stroke:#6c7086,stroke-width:1px,color:#cdd6f4;
    classDef highlight fill:#fab387,stroke:#e64553,stroke-width:2px,color:#11111b;
    classDef ingress fill:#a6e3a1,stroke:#40a02b,stroke-width:2px,color:#11111b;

    class ORCH,OBS,TOOL,INF,A2A layer;
    class HA highlight;
    class INGRESS ingress;

    %% Edge Styling Adjustments
    linkStyle 0,1,2 stroke:#a6e3a1,stroke-width:2px,color:#a6e3a1
    linkStyle 3,4 stroke:#a6e3a1,stroke-width:2px,color:#a6e3a1
    linkStyle 5,6,7,8,9,10,11,12 stroke:#89b4fa,stroke-width:2px,color:#89b4fa
    linkStyle 13,14,15,16,17,18 stroke:#6c7086,stroke-width:1px,stroke-dasharray:5
    linkStyle 19 stroke:#f38ba8,stroke-width:3px,color:#f38ba8
    linkStyle 20,21,22,23 stroke:#cba6f7,stroke-width:2px,color:#cba6f7
    linkStyle 24,25,26 stroke:#f9e2af,stroke-width:3px,color:#f9e2af
```

## How the system works

1. A monitoring system sends a JSON payload to `POST /webhook/alerts`.
2. The API assigns a UUID session ID and stores the payload as a `pending` queue row.
3. The worker atomically claims the oldest eligible row with `FOR UPDATE SKIP LOCKED` and marks it
   `processing`. Up to three jobs can run concurrently in one worker process.
4. The triage agent extracts the service, severity, timestamp, and error summary with Ollama.
5. The investigator queries the configured MySQL and Elasticsearch MCP servers, rejects mutating
   investigation calls, and synthesizes a root cause and mitigation plan.
6. LangGraph checkpoints the state in PostgreSQL and interrupts at the approval node. The worker
   changes the queue status to `awaiting_approval`.
7. An operator reviews the checkpoint through the API and approves or rejects the plan. The worker
   claims the updated queue row and resumes the same LangGraph thread.
8. An approval enables the mutation-capable mitigation executor; rejection ends the workflow without
   automated mitigation. After execution, the engineer uses read-only tools to verify recovery and
   either completes the incident or loops back to investigation.

### Main components

| Component | Location | Responsibility |
|---|---|---|
| FastAPI service | `main.py` | Alert ingestion, incident review, and approval decisions |
| Queue worker | `worker.py` | Claims queue rows, invokes/resumes LangGraph, and records outcomes |
| Workflow | `src/graph/` | Shared state, graph nodes, routing, and PostgreSQL checkpointing |
| Agents | `src/agents/` | Triage, investigation, approval, execution, and verification logic |
| MCP integration | `src/_mcp/` | MySQL, Elasticsearch, and local memory tool connections |
| Database | `src/db/` | Queue schema and ordered SQL migrations |
| Observability | `src/observability/` | Optional Langfuse callback and trace configuration |

### Queue states

| Status | Meaning |
|---|---|
| `pending` | Alert is ready for its first graph invocation |
| `processing` | A worker has claimed the incident |
| `awaiting_approval` | Graph state is checkpointed at the human approval gate |
| `auto_mitigation_approved` | Operator approved the plan; worker may resume execution |
| `manual_mitigation_required` | Operator rejected automation; worker resumes and ends safely |
| `completed` | The resumed workflow reached its terminal state |
| `failed` | Processing raised an exception; `retry_count` was incremented |

## Technology stack

Runtime versions below are the exact pins in `requirements.txt`; development-tool versions come from
`requirements-dev.txt`. Ollama, PostgreSQL, MySQL, Elasticsearch, and external MCP executables are
runtime services and are not version-pinned by this repository.

| Package | Version | Role |
|---|---:|---|
| Python | 3.12 | Supported application runtime |
| LangGraph | 1.1.0 | Stateful workflow orchestration |
| LangGraph Checkpoint PostgreSQL | 3.1.0 | Durable graph checkpoints in PostgreSQL |
| LangGraph Checkpoint | 4.1.1 | Checkpoint interfaces used by LangGraph |
| LangGraph Prebuilt | 1.0.8 | Prebuilt graph and agent utilities |
| LangChain Core | 1.3.3 | Messages, tools, and core agent abstractions |
| LangChain Ollama | 1.0.0 | Ollama chat-model integration |
| LangChain MCP Adapters | 0.3.0 | MCP tools exposed as LangChain tools |
| MCP | 1.28.1 | Model Context Protocol SDK and local server support |
| A2A SDK | 0.3.25 | Planned agent-to-agent integration |
| FastAPI (standard) | 0.139.2 | HTTP API and server extras |
| Pydantic | 2.13.4 | Request and structured-output validation |
| Psycopg | 3.3.4 | Asynchronous PostgreSQL driver |
| Psycopg Pool | 3.3.1 | Asynchronous database connection pooling |
| python-dotenv | 1.2.2 | Local `.env` loading |
| Langfuse | 4.14.1 | Optional LLM and workflow tracing |
| Black (development) | 26.5.1 | Code formatting |
| isort (development) | 8.0.1 | Import ordering |

## Requirements

- Python 3.12 and `pip`;
- PostgreSQL reachable by both the API and worker;
- Ollama with the configured model downloaded;
- a MySQL MCP server executable and `uvx` for the Elasticsearch MCP server; and
- access to the MySQL and Elasticsearch instances that will be investigated.

The MCP adapter currently contains a Windows-specific absolute path for the MySQL MCP executable in
`src/_mcp/adapter.py`. Change both MySQL `command` entries to the executable path for your machine
before starting the application. `uvx` must also be on `PATH`. These external MCP server packages are
not installed by `requirements.txt`.

### Hardware guidance

Memory requirements depend primarily on the Ollama model and its quantization. Treat these as starting
points and confirm them against the model build you deploy.

| Setup | RAM | VRAM | Model | Notes |
|---|---:|---:|---|---|
| Minimum GPU | 16 GB | 8 GB | `qwen2.5:7b` | Suitable for development and functional checks |
| Recommended GPU | 32 GB | 24 GB | larger tool-capable model | More headroom and stronger tool calling |
| CPU only | 32 GB | None | `qwen2.5:7b` | Supported by Ollama but substantially slower |

## Local development

The commands below use Bash from the repository root.

### 1. Create the environment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Do not commit `.env`; it may contain database and observability credentials.

### 2. Configure services

Edit `.env`:

| Variable | Required | Default/example | Purpose |
|---|---|---|---|
| `POSTGRES_CONNECTION_URI` | Yes | `postgresql://user:pass@localhost:5432/db` | Queue and checkpoint database |
| `OLLAMA_MODEL` | Yes | `qwen2.5:7b` | Model used by the agents |
| `OLLAMA_BASE_URL` | Yes | `http://localhost:11434` | Ollama API endpoint |
| `FASTAPI_ENV` | No | `development` | Environment label; currently not read by the code |
| `MYSQL_HOST` | Yes for MCP | `localhost` | Target MySQL host |
| `MYSQL_PORT` | Yes for MCP | `3306` | Target MySQL port |
| `MYSQL_USER` | Yes for MCP | `root` | Target MySQL user |
| `MYSQL_PASSWORD` | Yes for MCP | empty | Target MySQL password |
| `MYSQL_DATABASE` | Yes for MCP | empty | Target MySQL database |
| `ELASTICSEARCH_HOSTS` | Yes for MCP | `https://localhost:9200` | Target Elasticsearch endpoint(s) |
| `ELASTICSEARCH_USERNAME` | As needed | empty | Elasticsearch username |
| `ELASTICSEARCH_PASSWORD` | As needed | empty | Elasticsearch password |
| `ELASTICSEARCH_VERIFY_CERTS` | No | `false` | Verify Elasticsearch TLS certificates |
| `LANGFUSE_PUBLIC_KEY` | No | empty | Enables tracing when paired with the secret key |
| `LANGFUSE_SECRET_KEY` | No | empty | Langfuse authentication secret |
| `LANGFUSE_HOST` | No | `http://localhost:3000` | Self-hosted or cloud Langfuse endpoint |

Use separate, least-privilege credentials for investigation and mitigation in production. The current
adapter passes the same MySQL credentials to read-only and mutation-capable agents, so database-side
permissions remain an essential safety boundary.

Start Ollama and download the configured model if needed:

```bash
ollama pull qwen2.5:7b
ollama serve
```

If Ollama is already running as a service, only the `pull` command is needed.

### 3. Initialize PostgreSQL

Create the database referenced by `POSTGRES_CONNECTION_URI`, then apply the ordered migrations:

```bash
python src/db/db.py
```

The API and worker also create LangGraph checkpoint tables on startup. The migration runner does not
maintain a history table, so its SQL files must remain idempotent.

### 4. Start the application

Run the API and worker in separate activated terminals:

```bash
fastapi dev main.py
```

```bash
python worker.py
```

The development API defaults to `http://127.0.0.1:8000`; interactive OpenAPI documentation is at
`http://127.0.0.1:8000/docs`.

### 5. Exercise the approval flow

```bash
response=$(curl --fail-with-body --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "service": "checkout-api",
    "severity": "critical",
    "summary": "Database latency exceeded the alert threshold"
  }' \
  http://127.0.0.1:8000/webhook/alerts)

printf '%s\n' "$response"
session_id=$(printf '%s' "$response" | python -c \
  'import json, sys; print(json.load(sys.stdin)["session_id"])')
```

Keep the returned `session_id`. Once the worker reaches the interrupt, list and inspect incidents:

```bash
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:8000/incident/awaiting-approval

curl --fail-with-body --silent --show-error \
  "http://127.0.0.1:8000/incident/${session_id}/review"
```

Approve automatic mitigation only after reviewing its payload:

```bash
curl --fail-with-body --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "{\"incident_id\": \"${session_id}\", \"approve\": true}" \
  http://127.0.0.1:8000/incident/approve
```

Set `approve` to `false` to reject automated mitigation and route the incident to manual handling.

## API reference

| Method | Path | Success | Description |
|---|---|---:|---|
| `POST` | `/webhook/alerts` | `202` | Enqueue an arbitrary JSON alert and return its session ID |
| `GET` | `/incident/awaiting-approval` | `200` | List all queue rows waiting for a decision |
| `GET` | `/incident/{incident_id}/review` | `200` | Read the approval payload from the graph checkpoint |
| `POST` | `/incident/approve` | `200` | Approve or reject an incident awaiting approval |

The approval request schema is:

```json
{
  "incident_id": "UUID returned by the webhook endpoint",
  "approve": true
}
```

Review returns `404` if no approval interrupt exists. Approval returns `404` if the incident is absent
or no longer awaiting approval, preventing stale decisions from overwriting newer state. The API has
no authentication; place it behind an authenticated gateway outside a trusted development network.

## Deployment

This repository does not currently include a Dockerfile, Compose file, Kubernetes manifests, or
infrastructure-as-code. A production deployment therefore consists of two Python processes plus the
required backing services.

### Production topology

- run `main.py` as a long-lived ASGI service behind TLS and authentication;
- run `worker.py` as a separate process using the same release and environment;
- use one shared PostgreSQL database for the ingress queue and graph checkpoints;
- provide worker access to Ollama, MySQL, Elasticsearch, and optional Langfuse;
- install the external MCP executables on the worker host; and
- inject credentials from a secret manager, never from the image or repository.

### Release procedure

1. Provision Python 3.12 and install the pinned dependencies into an isolated environment.
2. Configure environment variables through the deployment platform.
3. Back up PostgreSQL and run `python src/db/db.py` once as a migration job.
4. Start the API with a production ASGI server:

   ```bash
   fastapi run main.py --host 0.0.0.0 --port 8000
   ```

5. Start `python worker.py` under the platform's process supervisor.
6. Verify connectivity and run one non-production alert through the approve/reject flow.

Multiple worker processes can safely claim different incidents because queue selection uses row locks
and `SKIP LOCKED`. Each worker permits three concurrent jobs. Capacity planning must include database
pool limits, Ollama concurrency, and MCP subprocesses. The code does not yet reclaim queue rows left
in `processing` after an abrupt worker failure, so operators must monitor and recover stale locks.

### Production hardening checklist

- authenticate and authorize every incident endpoint, especially approval;
- restrict webhook sources and enforce request-size limits;
- split read-only investigator credentials from executor credentials;
- enable TLS certificate verification for Elasticsearch;
- add health/readiness endpoints and centralized structured logging;
- monitor `failed`, long-running `processing`, and `awaiting_approval` rows;
- define PostgreSQL backup, restore, retention, and rollback procedures; and
- pin and audit external Ollama and MCP server versions.

## Testing and code quality

The repository currently uses `unittest` and does not pin pytest:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
black --check .
isort --check-only .
```

Apply formatting with `black .` and `isort .`. New tests should mock Ollama, PostgreSQL, MCP, and
Langfuse at unit boundaries. If pytest is adopted, add it to `requirements-dev.txt` first.

## Operations and troubleshooting

### API or worker cannot start

Confirm `POSTGRES_CONNECTION_URI` is present, the database exists, credentials are valid, and the host
is reachable. Both processes open a PostgreSQL pool and initialize checkpoint tables during startup.

### Incidents remain pending

The worker must run independently from the API. Inspect its output for PostgreSQL, Ollama, MCP
executable, or tool-startup errors. The polling loop waits five seconds after a queue-level error.

### Investigation reports no tools

Verify the hard-coded MySQL MCP executable path in `src/_mcp/adapter.py`, ensure `uvx` is on `PATH`,
and validate MySQL and Elasticsearch variables in the worker environment. Tool failures cause the
workflow to fail closed instead of inventing investigation evidence.

### No Langfuse traces appear

Tracing is disabled unless both Langfuse keys are non-empty. Verify the keys and `LANGFUSE_HOST`. The
incident workflow continues without tracing when Langfuse is not configured.

### Safety notes

The investigator and verification agents reject tool calls whose names or arguments appear mutating,
while the executor receives mutation-capable tools only after approval. These checks are defense in
depth, not a security boundary. Enforce policy with separate users, MCP configuration, network
controls, authentication, and an auditable approval process.
