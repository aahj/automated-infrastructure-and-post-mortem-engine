import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from _mcp.adapter import get_tools
from constants import Agents

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

EXECUTOR_PROMPT = """
You are the **Mitigation Executor Agent**, a specialized automated site reliability engineer responsible for executing pre-approved recovery commands during live system incidents.

### MISSION
Your sole objective is to safely translate approved remediation strategies into precise tool executions (e.g., reloading PM2 services, executing targeted MySQL query terminations, or clearing cache instances). You operate strictly within the boundaries of approved actions.

---

### INCIDENT CONTEXT
- **Incident ID:** {incident_id}
- **Service Name:** {service_name}
- **Severity Level:** {severity_level}
- **Occurred At (UTC):** {incident_occurred_at}

### DIAGNOSTIC SYNTHESIS
- **Error Summary:** {error_summary}
- **Root Cause Analysis:** {root_cause}
- **Diagnostics:** {diagnostics}

---

### OPERATING RULES & GUARDRAILS
1. **Targeted Execution:** Execute ONLY the tools required to address the identified `root_cause` for `{service_name}`. Do NOT run exploratory queries or unrequested system modifications.
2. **No Shell Injections:** Never construct arbitrary shell strings. Use provided tool interfaces exclusively.
3. **Execution Summary:** Once all necessary tool calls complete, produce a concise, structured summary detailing the exact commands invoked, target IDs/processes, and immediate tool return codes.

---

### OUTPUT FORMAT
After executing all required tool calls, provide your final response structured as follows:

**Execution Summary:**
- **Action(s) Taken:** [List of actions executed, e.g., "Reloaded PM2 process: payment-api", "Killed MySQL thread: 4821"]
- **Tools Invoked:** [List tool names and parameters used]
- **Tool Output Status:** [SUCCESS / FAILURE with brief result snippet]
- **Handoff Note:** "Mitigation steps applied. Handing off to Health Verifier for post-action verification loop."
"""
HUMAN_PROMPT = """
Review the conversation history and human approval payload below to identify the exact approved mitigation steps.
"""


async def get_mitigation_executor_tools() -> list[BaseTool]:
    tools = await get_tools(agent=Agents.MITIGATION_EXECUTOR)
    if not tools:
        raise ValueError("NO TOOL FOUND")
    return tools


async def build_llm() -> ChatOllama:
    tools = await get_mitigation_executor_tools()

    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=MODEL_NAME,
        temperature=0.1,  # 0.1 for deterministic tool selection and execution
    ).bind_tools(tools)


async def mitigation_executor_node(state: dict) -> dict:
    """
    LangGraph Node: Mitigation Executor
    Reads: state["service_name"], state["severity_level"], state["incident_occurred_at"], state["error_summary"], state["raw_alert_payload"], state["messages"], state["root_cause"], state["diagnostics"]
    Writes: state["internal_error"], state["current_status"]
    """
    service_name = state["service_name"]
    severity_level = state["severity_level"]
    incident_occurred_at = state["incident_occurred_at"]
    error_summary = state["error_summary"]
    raw_alert_payload = state["raw_alert_payload"]
    existing_messages = state.get("messages", [])
    root_cause = state["root_cause"]
    diagnostics = state["diagnostics"]

    required_fields = [
        service_name,
        severity_level,
        incident_occurred_at,
        error_summary,
        raw_alert_payload,
        root_cause,
        diagnostics,
    ]
    missing_fields = [f for f in required_fields if not f]
    if missing_fields:
        return {"internal_error": f"Missing required fields: {missing_fields}"}

    print("[MITIGATION EXECUTOR] " "Mitigating the issue....")

    try:
        llm = await build_llm()
    except ValueError:
        print("[MITIGATION EXECUTOR] " "NO TOOL FOUND, EXITING NOW....")
        return {"internal_error": "NO TOOL FOUND. EXITING NOW...."}
    system_prompt = SystemMessage(
        content=EXECUTOR_PROMPT.format(
            service_name=service_name,
            severity_level=severity_level,
            incident_occurred_at=incident_occurred_at,
            error_summary=error_summary,
            raw_alert_payload=str(raw_alert_payload),
            root_cause=root_cause,
            diagnostics=str(diagnostics),
        )
    )
    filtered_history = [msg for msg in existing_messages if msg.type != "system"]

    # Check if this is the first time the node is running
    is_first_iteration = not any(
        isinstance(msg, HumanMessage) and msg.content == HUMAN_PROMPT
        for msg in reversed(existing_messages)
    )
    print("[MITIGATION EXECUTOR] " f"Calling Model: {MODEL_NAME}")

    new_messages = []
    if is_first_iteration:
        new_messages = [system_prompt, HumanMessage(content=HUMAN_PROMPT)]

    input_to_llm = filtered_history + new_messages

    try:
        response = await llm.ainvoke(input_to_llm)
    except Exception as e:
        print(f"[MITIGATION EXECUTOR] LLM invoke error: {e}")
        return {"internal_error": str(e)}

    return {
        "current_status": "mitigating",
        "internal_error": None,
        "messages": new_messages + [response],
    }
