import json
import os
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from _mcp.adapter import get_tools
from constants import MAX_INVESTIGATOR_TOOL_ROUNDS, MUTATING_OPERATION_REGEX, Agents

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MAX_TOOL_ROUNDS = MAX_INVESTIGATOR_TOOL_ROUNDS
MUTATING_OPERATION_OPERATION = re.compile(MUTATING_OPERATION_REGEX, re.IGNORECASE)


class InvestigatorResult(BaseModel):
    """Structured outcome used by LangGraph"""

    root_cause: str = Field(
        description="A concise, probabilistic statement (e.g., '85% probability: DB connection pool exhaustion caused by unindexed orders query')"
    )
    diagnostics: dict[str, Any] = Field(
        description="Key traces, metric anomalies, and failing queries found."
    )


SYNTHESIZER_PROMPT = """
You are the Evidence Synthesizer. Gather evidence from this conversation. Your goal is to identify the root cause of the incident and provide key diagnostics.
Rules:
- Never invent evidence.
"""

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

HUMAN_PROMPT = "Investigate the issue"


async def get_log_investigator_tools() -> list[BaseTool]:
    tools = await get_tools(agent=Agents.LOG_INVESTIGATOR)
    return tools or []


def _error_result(message: str) -> dict:
    return {
        "internal_error": message,
        "current_status": "investigating",
    }


def _is_read_only_tool_call(tool_name: str, arguments: dict) -> bool:
    """Reject tool calls whose name or arguments indicate a state mutation."""
    normalized_name = tool_name.replace("_", " ").replace("-", " ")
    call_description = f"{normalized_name} {json.dumps(arguments, default=str)}"
    return MUTATING_OPERATION_OPERATION.search(call_description) is None


async def log_investigator_node(state: dict) -> dict:
    """
    LangGraph Node: Log Investigator

    Reads: state["service_name"], state["severity_level"], state["incident_occurred_at"], state["error_summary"], state["raw_alert_payload"], state["messages"]
    Writes: state["internal_error"], state["current_status"]
    """
    print("[LOG INVESTIGATOR] " "Investigating the issue....")

    service_name = state["service_name"]
    severity_level = state["severity_level"]
    incident_occurred_at = state["incident_occurred_at"]
    error_summary = state["error_summary"]
    raw_alert_payload = state["raw_alert_payload"]
    existing_messages = state.get("messages", [])

    if not severity_level or not incident_occurred_at or not error_summary or not raw_alert_payload:
        return _error_result(
            "Either raw alert payload, severity level or incident occurrence timestamp not provided"
        )

    tools = await get_log_investigator_tools()
    if not tools:
        return _error_result("NO TOOL FOUND. Hence can't investigate the logs, EXITING NOW....")

    llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=MODEL_NAME,
        temperature=0.1,  # 0.1 for deterministic tool diagnostic
    ).bind_tools(tools)
    system_prompt = SystemMessage(
        content=INVESTIGATOR_PROMPT.format(
            service_name=service_name,
            severity_level=severity_level,
            incident_occurred_at=incident_occurred_at,
            error_summary=error_summary,
            raw_alert_payload=json.dumps(raw_alert_payload, default=str),
        )
    )
    setup_messages = [system_prompt, HumanMessage(content=HUMAN_PROMPT)]
    generated_messages = list(setup_messages)
    conversation = [msg for msg in existing_messages if msg.type != "system"] + setup_messages
    tool_map = {tool.name: tool for tool in tools}
    print("[LOG INVESTIGATOR] " f"Calling Model: {MODEL_NAME}")

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
                if not _is_read_only_tool_call(tool_call["name"], args):
                    content = _error_result(
                        f"Tool call rejected due to potential state mutation: {tool_call['name']} with args: {args}"
                    )
                elif tool is None:
                    content = _error_result(f"No tool is available: {tool_call["name"]}")
                else:
                    try:
                        print(
                            "[LOG INVESTIGATOR] "
                            f"Calling tool: {tool_call['name']} with args: {args}"
                        )
                        result = await tool.ainvoke(args)
                        content = (
                            result if isinstance(result, str) else json.dumps(result, default=str)
                        )
                    except Exception as e:
                        print(f"[LOG INVESTIGATOR] Tool calling failed: {e}")
                        content = f"Tool calling failed: {type(e).__name__}: {str(e)}"

                tool_message = ToolMessage(content=content, tool_call_id=tool_call["id"])
                conversation.append(tool_message)
                generated_messages.append(tool_message)
    except Exception as e:
        print(f"[LOG INVESTIGATOR] LLM invoke error: {e}")
        result = _error_result(f"Log investigator failed: {str(e)}")
        result["messages"] = generated_messages
        return result

    synthesizer_llm = ChatOllama(
        base_url=OLLAMA_BASE_URL, model=MODEL_NAME, temperature=0
    ).with_structured_output(InvestigatorResult)
    print(f"[LOG INVESTIGATOR] Calling Synthesizer Model: {MODEL_NAME}")

    try:
        synthesizer_response = synthesizer_llm.ainvoke(
            conversation + [HumanMessage(content=SYNTHESIZER_PROMPT)]
        )
        if not isinstance(synthesizer_response, InvestigatorResult):
            synthesizer_response = InvestigatorResult.model_validate(synthesizer_response)
    except Exception as exc:
        print(f"[LOG INVESTIGATOR] Evidence Synthesis failed: {exc}")
        result = _error_result(f"Could not synthesize evidence: {exc}")
        result["messages"] = generated_messages
        return result
    
    print(f"[LOG INVESTIGATOR] Evidence Synthesized: {synthesizer_response.model_dump_json()}")

    evidence_message = AIMessage(content=synthesizer_response.model_dump_json())

    return {
        "messages": generated_messages + [evidence_message],
        "internal_error": None,
        "current_status": "awaiting_approval",
        "root_cause": synthesizer_response.root_cause,
        "diagnostics": synthesizer_response.diagnostics,
    }
