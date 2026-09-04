import json
import os

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from _mcp.adapter import get_tools
from constants import MAX_EXECUTOR_TOOL_ROUNDS, Agents

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MAX_TOOL_ROUNDS = MAX_EXECUTOR_TOOL_ROUNDS
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
    return tools or []


def _tool_error_result(message: str) -> dict:
    return {
        "internal_error": message,
        "current_status": "failed_mitigation",
    }


async def mitigation_executor_node(state: dict) -> dict:
    """
    LangGraph Node: Mitigation Executor
    Reads: state["service_name"], state["severity_level"], state["incident_occurred_at"], state["error_summary"], state["raw_alert_payload"], state["messages"], state["root_cause"], state["diagnostics"]
    Writes: state["internal_error"], state["current_status"]
    """
    incident_id = state["incident_id"]
    service_name = state["service_name"]
    severity_level = state["severity_level"]
    incident_occurred_at = state["incident_occurred_at"]
    error_summary = state["error_summary"]
    raw_alert_payload = state["raw_alert_payload"]
    existing_messages = state.get("messages", [])
    root_cause = state["root_cause"]
    diagnostics = state["diagnostics"]

    required_fields = [
        incident_id,
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

    tools = await get_mitigation_executor_tools()
    if not tools:
        return _tool_error_result("NO TOOL FOUND. EXITING NOW..")

    llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=MODEL_NAME,
        temperature=0,  # 0 for deterministic tool selection and execution
    ).bind_tools(tools)
    system_prompt = SystemMessage(
        content=EXECUTOR_PROMPT.format(
            incident_id=incident_id,
            service_name=service_name,
            severity_level=severity_level,
            incident_occurred_at=incident_occurred_at,
            error_summary=error_summary,
            raw_alert_payload=json.dumps(raw_alert_payload, default=str),
            root_cause=root_cause,
            diagnostics=json.dumps(diagnostics, default=str),
        )
    )
    setup_messages = [system_prompt, HumanMessage(content=HUMAN_PROMPT)]
    generated_messages = list(setup_messages)
    conversation = [msg for msg in existing_messages if msg.type != "system"] + setup_messages
    tool_map = {tool.name: tool for tool in tools}
    print("[MITIGATION EXECUTOR] " f"Calling Model: {MODEL_NAME}")
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = await llm.ainvoke(conversation)
            conversation.append(response)
            generated_messages.append(response)
            if not response.tool_calls:
                break
            for tool_call in response.tool_calls:
                tool = tool_map.get(tool_call["name"])
                args = tool_call.get("args", {})
                if tool is None:
                    content = _tool_error_result(f"No tool is available: {tool_call['name']}")
                else:
                    try:
                        print(
                            "[MITIGATION EXECUTOR] "
                            f"Calling tool: {tool_call['name']} with args: {args}"
                        )
                        result = await tool.ainvoke(args)
                        content = (
                            result if isinstance(result, str) else json.dumps(result, default=str)
                        )
                    except Exception as exc:
                        print(f"[MITIGATION EXECUTOR] Tool calling failed: {exc}")
                        content = f"Tool calling failed: {type(exc).__name__}: {str(exc)}"
                tool_message = ToolMessage(content=content, tool_call_id=tool_call["id"])
                conversation.append(tool_message)
                generated_messages.append(tool_message)
    except Exception as e:
        print(f"[MITIGATION EXECUTOR] LLM invoke error: {e}")
        result = _tool_error_result(f"Mitigation Executor Failed: {str(e)}")
        result["messages"] = generated_messages
        return result

    return {"current_status": "mitigating", "internal_error": None, "messages": generated_messages}
