import os

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from _mcp.adapter import get_tools
from constants import Agents

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

INVESTIGATOR_PROMPT = """
You are a read-only incident investigator.

Your responsibility is to gather evidence using the available tools.

Rules

- Never fabricate logs.
- Never fabricate metrics.
- Never fabricate traces.
- Always use tools before making conclusions.
- If evidence is insufficient, explicitly record the ambiguity.
- Do not generate the final incident report.
- Another agent will summarize your findings.


INPUT DATA
You will receive incident data structured as follow:
- **SERVICE NAME:** {service_name}
- **SEVERITY LEVEL:** {severity_level}
- **INCIDENT TIMESTAMP:** {incident_occurred_at}
- **ERROR SUMMARY:** {error_summary}
- **RAW ALERT PAYLOAD:** {raw_alert_payload}

---

Workflow

1. Retrieve relevant logs.
2. Retrieve metrics if needed.
3. Retrieve traces if needed.
4. Correlate evidence.
5. Produce:

- evidence
- observations
- hypotheses
- ambiguities
"""


async def get_log_investigator_tools() -> list[BaseTool]:
    tools = await get_tools(agent=Agents.LOG_INVESTIGATOR)
    if not tools:
        raise ValueError("NO TOOL FOUND")
    return tools


async def build_investigation_tool_llm() -> ChatOllama:
    tools = await get_log_investigator_tools()

    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=MODEL_NAME,
        temperature=0.1,  # 0.1 for deterministic tool diagnostic
    ).bind_tools(tools)


async def log_investigator_node(state: dict) -> dict:
    """
    LangGraph Node: Log Investigator

    Reads: state["service_name"], state["severity_level"],state["incident_ocuured_at"],state["error_summary"],state["raw_alert_payload"]
    Writes: state["internal_error"]
    """
    service_name = state["service_name"]
    severity_level = state["severity_level"]
    incident_occurred_at = state["incident_ocuured_at"]
    error_summary = state["error_summary"]
    raw_alert_payload = state["raw_alert_payload"]

    print(
        {
            "service_name": service_name,
            "severity_level": severity_level,
            "incident_occurred_at": incident_occurred_at,
            "error_summary": error_summary,
            "raw_alert_payload": raw_alert_payload,
        }
    )

    if not severity_level or not incident_occurred_at or not error_summary or not raw_alert_payload:
        return {
            "internal_error": "Either raw alert payload, severity level or incident occurrence timestamp not provided"
        }

    print("[LOG INVESTIGATOR] " "Investigating the issue....")

    try:
        llm = await build_investigation_tool_llm()
    except ValueError:
        print("[LOG INVESTIGATOR] " "NO TOOL FOUND, EXITING NOW....")
        return {
            "internal_error": "NO TOOL FOUND. Hence can't investigate the logs, EXITING NOW...."
        }

    messages = [
        SystemMessage(
            content=INVESTIGATOR_PROMPT.format(
                service_name=service_name,
                severity_level=severity_level,
                incident_occurred_at=incident_occurred_at,
                error_summary=error_summary,
                raw_alert_payload=str(raw_alert_payload),
            )
        ),
        HumanMessage(content="Investigate the issue"),
    ]

    print("[LOG INVESTIGATOR] " f"Calling Model: {MODEL_NAME}")

    try:
        result = await llm.ainvoke(messages)
    except Exception as e:
        print("[LOG INVESTIGATOR] " f"LLM invoke error: {str(e)}")
        return {"internal_error": str(e), "messages": messages}

    # if tools calls required
    if result.tool_calls:
        print("[LOG INVESTIGATOR] " f"LLM requires tool calling: {str(result.tool_calls)}\n")
        return {"messages": [result]}

    print("[LOG INVESTIGATOR] " "LLM have investigated the alert incident")

    return {"messages": [result], "internal_error": None}
