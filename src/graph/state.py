from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class AgentState(TypedDict):
    """
    The shared agent state for Automated Infrastructure and Post-Mortem graph

    When Node returns {"is_resolved": true}, LangGraph merges that into existing
    states, instead of replacing the whole dict.
    Node only returns the changed key

    Moreover, the `messages` is annotated with `add_messages` reducer,
    which appends to the list instead of overwrite.

    """

    messages: Annotated[list[BaseMessage], add_messages]
    session_id: str
    incident_id: str
    service_name: str
    severity_level: str  # levels: "critical", "warning", "info"
    incident_occurred_at: str  # utc timestamp in string
    raw_alert_payload: dict
    error_summary: str  # given by triage node
    current_status: str  # ["triaged","investigating","awaiting_approval","mitigating","resolved","failed_mitigation"]
    root_cause: str  # given by Evidence Synthesizer node
    diagnostics: dict  # {"app_logs":[...], "db_logs":[...]}  - given by Evidence Synthesizer Node
    is_resolved: bool
    mitigation_plan: list[dict]
    verification_result: dict
    final_report: str  # in markdown format
    internal_error: str | None
    approved: bool  # human approval


def initial_state(raw_alert_payload: dict, session_id: str, incident_occurred_at: str) -> dict:
    """Create initial state"""
    return {
        "messages": [],
        "session_id": session_id,
        "incident_id": session_id,
        "service_name": "",
        "severity_level": "",
        "incident_occurred_at": incident_occurred_at,
        "raw_alert_payload": raw_alert_payload,
        "error_summary": "",
        "current_status": "",
        "root_cause": "",
        "diagnostics": {},
        "is_resolved": False,
        "mitigation_plan": [],
        "verification_result": {},
        "final_report": "",
        "internal_error": None,
        "approved": False,
    }
