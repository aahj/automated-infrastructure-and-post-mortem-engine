import json
import os
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from _mcp.adapter import get_tools
from constants import MAX_ENGINEER_TOOL_ROUNDS, Agents

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MAX_VERIFICATION_TOOL_ROUNDS = MAX_ENGINEER_TOOL_ROUNDS
MUTATING_OPERATION_PATTERN = re.compile(
    r"\b(delete|drop|insert|kill|post|put|patch|reload|restart|terminate|truncate|update|write)\b",
    re.IGNORECASE,
)


class VerificationResult(BaseModel):
    """Structured outcome used by LangGraph's mitigation router."""

    is_resolved: bool = Field(description="True only when post-action evidence proves recovery")
    summary: str = Field(description="Concise explanation of the resolution decision")
    checks_performed: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


VERIFICATION_PROMPT = """
You are the Mitigation Engineer. The MITIGATION ENGINEER has already applied the approved
changes. Your only job is to verify recovery; never execute a mutation or assume that a
successful command means the incident is resolved.

Incident: {incident_id}
Service: {service_name}
Root cause: {root_cause}
Pre-mitigation diagnostics/baseline: {diagnostics}

Run one or more available read-only post-action checks:
1. Probe process state, resource stability, restart-count deltas, and crash loops.
2. Call the internal HTTP health endpoint and verify 200 status and acceptable latency.
3. Query logs/metrics from the 30-60 seconds after mitigation and compare error rates with
   the baseline.
4. Re-query database processes, locks, blocked threads, and connection-pool pressure.

Prefer checks relevant to the root cause. Use multiple independent checks when available.
If tools are missing, return errors, or provide ambiguous/stale evidence, recovery is not
proven. Do not call write, kill, reload, restart, or other mitigation tools.
"""

DECISION_PROMPT = """
Evaluate only the post-action tool results in this conversation. Set is_resolved=true only
when at least one successful, current health check directly confirms recovery and no check
shows a continuing failure. Treat missing evidence, tool errors, crash loops, unhealthy HTTP
responses, elevated post-fix errors, remaining locks, or saturated pools as unresolved.
Summarize the concrete evidence and list every check performed or failed.
"""


async def get_mitigation_engineer_tools() -> list[BaseTool]:
    tools = await get_tools(agent=Agents.MITIGATION_ENGINEER)
    return tools or []


def _tool_error_result(message: str) -> dict:
    return {
        "is_resolved": False,
        "current_status": "failed_mitigation",
        "internal_error": message,
        "verification_result": {
            "is_resolved": False,
            "summary": message,
            "checks_performed": [],
            "failed_checks": [message],
            "evidence": {},
        },
        "tool_iterations": 0,
    }


def is_read_only_tool_call(tool_name: str, arguments: dict) -> bool:
    """Reject tool calls whose name or arguments indicate a state mutation."""

    normalized_name = tool_name.replace("_", " ").replace("-", " ")
    call_description = f"{normalized_name} {json.dumps(arguments, default=str)}"
    return MUTATING_OPERATION_PATTERN.search(call_description) is None


async def mitigation_engineer_node(state: dict) -> dict:
    """Run read-only post-action probes, then make a structured resolution decision."""
    print("[MITIGATION ENGINEER] " "Mitigating the issue....")

    tools = await get_mitigation_engineer_tools()
    if not tools:
        return _tool_error_result("No read-only verification tools are available")

    prompt = VERIFICATION_PROMPT.format(
        incident_id=state.get("incident_id", "unknown"),
        service_name=state.get("service_name", "unknown"),
        root_cause=state.get("root_cause", "unknown"),
        diagnostics=json.dumps(state.get("diagnostics", {}), default=str),
    )
    setup_messages = [
        SystemMessage(content=prompt),
        HumanMessage(content="Run post-action checks now."),
    ]
    conversation = [
        message for message in state.get("messages", []) if message.type != "system"
    ] + setup_messages
    tool_map = {tool.name: tool for tool in tools}
    tool_llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=MODEL_NAME,
        temperature=0,
    ).bind_tools(tools)
    generated_messages = list(setup_messages)
    completed_checks = 0
    print("[MITIGATION ENGINEER] " f"Calling Model: {MODEL_NAME}")

    try:
        for _ in range(MAX_VERIFICATION_TOOL_ROUNDS):
            response = await tool_llm.ainvoke(conversation)
            conversation.append(response)
            generated_messages.append(response)

            if not response.tool_calls:
                break

            for tool_call in response.tool_calls:
                tool = tool_map.get(tool_call["name"])
                arguments = tool_call.get("args", {})
                if not is_read_only_tool_call(tool_call["name"], arguments):
                    content = "Blocked non-read-only operation during verification"
                elif tool is None:
                    content = f"Verification tool is not available: {tool_call['name']}"
                else:
                    try:
                        print(
                            "[MITIGATION ENGINEER] "
                            f"Calling tool: {tool_call['name']} with args: {arguments}"
                        )
                        result = await tool.ainvoke(arguments)
                        content = (
                            result if isinstance(result, str) else json.dumps(result, default=str)
                        )
                        completed_checks += 1
                    except Exception as exc:
                        print(f"[MITIGATION ENGINEER] Tool calling failed: {exc}")
                        content = f"Verification tool failed: {type(exc).__name__}: {exc}"

                tool_message = ToolMessage(content=content, tool_call_id=tool_call["id"])
                conversation.append(tool_message)
                generated_messages.append(tool_message)
    except Exception as exc:
        print(f"[MITIGATION ENGINEER] LLM invoke error: {exc}")
        result = _tool_error_result(f"Post-action verification failed: {exc}")
        result["messages"] = generated_messages
        return result

    if completed_checks == 0:
        result = _tool_error_result("No post-action health check completed successfully")
        result["messages"] = generated_messages
        return result

    decision_llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=MODEL_NAME,
        temperature=0,
    ).with_structured_output(VerificationResult)
    print(f"[MITIGATION ENGINEER] Calling Decision Model: {MODEL_NAME}")

    try:
        decision = await decision_llm.ainvoke(
            conversation + [HumanMessage(content=DECISION_PROMPT)]
        )
        if not isinstance(decision, VerificationResult):
            decision = VerificationResult.model_validate(decision)
    except Exception as exc:
        print(f"[MITIGATION ENGINEER] Decision evaluation failed: {exc}")
        result = _tool_error_result(f"Could not evaluate verification evidence: {exc}")
        result["messages"] = generated_messages
        return result

    decision_message = AIMessage(content=decision.model_dump_json())
    return {
        "messages": generated_messages + [decision_message],
        "is_resolved": decision.is_resolved,
        "current_status": "resolved" if decision.is_resolved else "failed_mitigation",
        "internal_error": None,
        "verification_result": decision.model_dump(),
        # A failed mitigation starts a fresh investigator ReAct budget.
        "tool_iterations": 0,
    }
