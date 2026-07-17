# Automated Infrastructure And Post-Mortem Engine
---
## The LangGraph Flow
```mermaid
graph TD
    %% Nodes
    START([START]) --> triage_commander[triage_commander<br>#40;Triage Commander#41;]
    
    triage_commander --> log_investigator[log_investigator<br>#40;Log & Metrics Investigator#41;]
    
    log_investigator --> human_approval{human_approval<br>#40;Human Approval Gate#41;}
    
    mitigation_engineer[mitigation_engineer<br>#40;Mitigation Engineer#41;]
    post_mortem_scribe[post_mortem_scribe<br>#40;Post-Mortem Scribe via A2A#41;]
    
    END([END])

    %% Edge Transitions
    human_approval -.->|approved = true| mitigation_engineer
    human_approval -.->|approved = false / rejected| END
    
    mitigation_engineer -.->|is_resolved = false / retry| log_investigator
    mitigation_engineer -.->|is_resolved = true| post_mortem_scribe
    
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
    subgraph INGRESS [INGRESS & TRIGGER GATEWAY]
        PROM[Prometheus / Grafana Alert] -->|HTTP POST Webhook| API[FastAPI Gateway]
        CW[AWS CloudWatch Alert] -->|HTTP POST Webhook| API
        PD[PagerDuty Webhook] -->|HTTP POST Webhook| API
    end

    %% Orchestration Layer (LangGraph)
    subgraph ORCH [ORCHESTRATION LAYER - LangGraph Stateful Workflow]
        direction TB
        
        %% Entry Node
        TP[triage_commander<br/>#40;Triage Commander#41;]
        
        %% Core Diagnostic Node (Read-Only)
        LI[log_investigator<br/>#40;Log & Metrics Investigator#41;]
        
        %% Stateful Intercept (Write-Protection Gate)
        HA{human_approval<br/>#40;Human Approval Gate#41;}
        
        %% Core Action & Report Nodes
        ME[mitigation_engineer<br/>#40;Mitigation Engineer#41;]
        PMS[post_mortem_scribe<br/>#40;Post-Mortem Scribe#41;]
        
        %% Flow Connections
        TP --> LI
        LI --> HA
        HA -->|Approved / Execute Plan| ME
        HA -->|Rejected / False Alarm| END_NODE([END])
        
        ME -->|Resolved| PMS
        ME -->|Failed / Needs More Data| LI
        PMS --> END_NODE
        
        %% Checkpoint Storage
        DB[(SQLite<br/>Checkpoint Store)] <--->|Persists State Per Node Execution| TP & LI & HA & ME & PMS
    end

    %% Webhook transfers raw payload straight to initial state graph execution
    API -->|1. graph.ainvoke#40;raw_alert_payload#41;| TP

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
```

**Agent 1:** Triage Commander (triage_commander) – Structure raw data, handles noisy payload ingestion and configures state routing.

**Agent 2:** Log & Metrics Investigator (log_investigator) – The diagnostic hunter. Loops through tools to isolate root causes.

**Agent 3:** Mitigation Engineer (mitigation_engineer) – Proposes/applies safe state fixes and checks performance recoveries against metrics targets.

**Agent 4:** Post-Mortem Scribe Client (post_mortem_scribe) – Captures final graph states and commands the cross-framework translation.

**Agent 5:** CrewAI Document Specialist (External) – Hosted as a microservice, specialized purely in writing readable, long-form post-mortem compliance reports using distinct framework capabilities.

### Key Architecture Connections
**MCP Integration:** The Tool Layer now houses separate MCP servers (Loki/Elastic MCP for application workloads, and a PostgreSQL MCP for direct database analysis). This enables the *log_investigator* to systematically step through the application logs, discover a DB timeout, and seamlessly query the database engine next

**A2A Delegation:** The *post_mortem_scribe* node acts as an A2A Client. It passes execution arrays over local JSON-RPC endpoints to the CrewAI framework service, allowing completely seamless cross-framework processing without tying CrewAI directly into your LangGraph engine.

**Quality & Observability Isolation:** Every single execution step, node switch, and model query automatically drops trace hooks down to Langfuse. When code adjustments or generated documentation reports wrap up, DeepEval steps in as an isolated asynchronous evaluator to run deterministic semantic validations against the output before completing the cycle.

---

## Technology stack
| Technology | Version | Role |
|------------|---------|------|
| LangGraph | 1.1.0 | Stateful multi-agent graph orchestration |
| MCP | 1.26.0 | Standardized agent-to-tool protocol |
| A2A SDK | 0.3.25 | Cross-framework agent-to-agent protocol |
| Ollama | latest | Local LLM inference (no API keys) |
| CrewAI | 1.13.0 | Cross-framework interop via A2A |
| Langfuse | 4.0.1 | Distributed tracing and observability |
| DeepEval | 3.9.1 | LLM-as-judge evaluation |

---

## Hardware Requirements
| Setup | RAM | VRAM | Model | Notes |
|--------|-----|------|-------|-------|
| Minimum | 16 GB | 8 GB | qwen2.5:7b | Fully functional |
| Recommended | 32 GB | 24 GB | qwen2.5-coder:32b | Best tool-calling reliability |
| CPU-only | 32 GB | None | qwen2.5:7b | Works but 5 to 10 times slower |

---

