import json
import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from constants import Agents
from _mcp.adapter import get_tools

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

PROMPT = """
You are the **Log Investigator Agent**, a specialized read-only diagnostic engineer in an automated incident response system.

### OBJECTIVE
Your sole responsibility is to investigate the root cause of an incoming infrastructure incident by querying observability tools, analyzing error telemetry, and constructing an evidence-backed diagnostic summary.

---

### OPERATIONAL GUARDRAILS (STRICT ENFORCEMENT)
1. **READ-ONLY AUTHORITY:** You are strictly forbidden from performing write or mutation actions (e.g., restarting services, modifying DB rows, altering autoscaling parameters).
2. **EVIDENCE-DRIVEN:** Never guess or hallucinate a root cause. Every claim MUST be backed by log traces, metrics, or DB state returned by your tools.
3. **NO CONTINUOUS LOOPS:** Limit your tool calls to a maximum of 8-10 diagnostic iterations. If logs are missing or inconclusive, explicitly state the ambiguity in your output.

---

### INVESTIGATION WORKFLOW
When invoked with an incident payload, follow this systematic flow:
1. **Time Windowing:** Identify the `incident_ocuured_at` from the payload and query logs/metrics within a tight window (e.g., ±5 minutes).
2. **Log & Metric Correlation:** 
   - Search for `ERROR` or `FATAL` level logs related to the affected service.
   - Correlate log spikes with resource metrics (e.g., high DB connection counts, memory leaks).
3. **Trace Pinpointing:** Extract specific stack traces, HTTP 5xx status codes, failing database queries, or trace IDs.
4. **Formulate Hypothesis:** Construct a probabilistic root-cause hypothesis backed by the gathered telemetry.

---

### OUTPUT FORMAT REQUIREMENTS
You must structure your analysis cleanly into the target JSON. The JSON must match this exact schema:
{
    "root_cause": "A concise, probabilistic statement (e.g., '85% probability: DB connection pool exhaustion caused by unindexed orders query')",
    "current_status": "investigating",
    "diagnostics" : "Key traces, metric anomalies, and failing queries found (e.g., {"app_logs":[...], "db_logs":[...]}). The type must be dict format"
}

Rules:
- current_status must always be set to "investigating"
"""

def parsing_llm_response_json(json_string: str) -> dict:
    """Parse LLM JSON output"""
    try:
        data = json.loads(json_string)
    except json.JSONDecodeError as e:
        raise ValueError(
            "LLM return invalid JSON.\n"
            f"Error: {e}\n"
            f"Printing first [300] char: {json_string[:300]}"
        )

    required_fields = ("root_cause", "diagnostics")
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing field in the LLM output: '{field}'")

    return data

async def build_log_investigator_llm() -> ChatOllama:
    tools = await get_tools(agent=Agents.LOG_INVESTIGATOR)
    if not tools:
        raise ValueError("NO TOOL FOUND")

    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=MODEL_NAME,
        format="json",
        temperature=0.3,
    ).bind_tools(tools)


async def log_investigator_node(state: dict) -> dict:
    """
    LangGraph Node: Log Investigator

    Reads: state["service_name"], state["severity_level"],state["incident_ocuured_at"],state["error_summary"],state["raw_alert_payload"]
    Writes: state["root_cause"], state["current_status"], state["diagnostics"], state["internal_error"]
    """
    service_name = state["service_name"]
    severity_level = state["severity_level"]
    incident_occurred_at = state["incident_ocuured_at"]
    error_summary = state["error_summary"]
    raw_alert_payload = state["raw_alert_payload"]

    print({service_name, severity_level, incident_occurred_at, error_summary, raw_alert_payload})

    if not severity_level or not incident_occurred_at or not error_summary or not raw_alert_payload:
        return {
            "internal_error": "Either raw alert payload, severity level or incident occurrence timestamp not provided"
        }

    print("[LOG INVESTIGATOR] " "Investigating the issue....")

    try:
        llm = await build_log_investigator_llm()
    except ValueError:
        print("[LOG INVESTIGATOR] " "NO TOOL FOUND, EXITING NOW....")
        return {
            "internal_error": "NO TOOL FOUND. Hence can't investigate the logs, EXITING NOW...."
        }

    messages = [
        SystemMessage(content=PROMPT),
        HumanMessage(content=f"""
        Investigate the incident for service [{service_name}], severity level [{severity_level}], incident occurred at [{incident_occurred_at}], error summary [{error_summary}],
        raw alert payload [{str(raw_alert_payload)}] .
        Begin by querying relevant logs.
        """),
    ]

    print("[LOG INVESTIGATOR] " f"Calling Model: {MODEL_NAME}")

    try:
        result = llm.invoke(messages)
    except Exception as e:
        print("[LOG INVESTIGATOR] " f"LLM invoke error: {str(e)}")
        return {"internal_error": str(e), "messages": messages}
    
    try:
        parsed_data = parsing_llm_response_json(result.content)
    except ValueError as e:
        print("[LOG INVESTIGATOR] " f"Parse error: {str(e)}")
        return {"internal_error": str(e), "messages": messages + [result]}

    print("[LOG INVESTIGATOR] " f"LLM have investigated the alert incident: {str(parsed_data)}")

    return {"messages": messages + [result], "internal_error": None, **parsed_data}

