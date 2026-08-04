import json
import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

PROMPT = """
You're an expert triage commander for a software engineering team. Your job is to transalate unstructured or messy incoming alert payloads into a structured format. 
Extract the service name, severity level and error summary from this raw alert payload.

RETURN only a valid JSON with no prose, no markdown code fences, no explanation.
The JSON must match this exact schema:

{
    "service_name": "The specific microservice, database, or infrastructure component flagged as the source of the anomaly (e.g., payment-service, auth-db)",
    "severity_level": "(e.g,. 'CRITICAL', 'WARNING', 'INFO')",
    "incident_occurred_at": "the timestamp in UTC when the incident was detected, in ISO 8601 format. If no timestamp is present, then leave it.",
    "error_summary": "A concise, generated title/summary of the issue used to seed human notifications.",
    "current_status": "triaged"
}

Rules:
- current_status must always be set to "triaged"
"""


def build_triage_llm() -> ChatOllama:
    # temperature=0.1. Very low, because structured JSON output needs consistency.
    #  A higher temperature introduces variation that makes JSON parsing unreliable.
    return ChatOllama(base_url=OLLAMA_BASE_URL, model=MODEL_NAME, format="json", temperature=0.1)


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

    required_fields = ("severity_level", "error_summary", "service_name")
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing field in the LLM output: '{field}'")

    return data


def triage_node(state: dict) -> dict:
    """
    LangGraph Node: Triage commander

    Reads: state["raw_alert_payload"]
    Writes: state["service_name"], state["severity_level"], state["incident_occurred_at"], state["error_summary"], state["internal_error"]
    """
    raw_alert_payload = state["raw_alert_payload"]
    default_incident_timestamp = state["incident_occurred_at"]  # timestamp from initial state

    if not raw_alert_payload:
        return {"internal_error": "No raw alert payload provided"}

    print("[TRIAGE COMMANDER] " f"Analyzing raw payload: {raw_alert_payload}")

    llm = build_triage_llm()
    messages = [SystemMessage(content=PROMPT), HumanMessage(content=str(raw_alert_payload))]

    print("[TRIAGE COMMANDER] " f"Calling Model: {MODEL_NAME}")

    try:
        result = llm.invoke(messages)
    except Exception as e:
        print("[TRIAGE COMMANDER] " f"LLM invoke error: {str(e)}")
        return {"internal_error": str(e), "messages": messages}

    try:
        parsed_data = parsing_llm_response_json(result.content)
    except ValueError as e:
        print("[TRIAGE COMMANDER] " f"Parse error: {str(e)}")
        return {"internal_error": str(e), "messages": messages + [result]}

    parsed_data["incident_occurred_at"] = (
        parsed_data["incident_occurred_at"] or default_incident_timestamp
    )

    print("[TRIAGE COMMANDER] " f"LLM have structured the alert payload: {str(parsed_data)}")

    return {"messages": messages + [result], "internal_error": None, **parsed_data}
