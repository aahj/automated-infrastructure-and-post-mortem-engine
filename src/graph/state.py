from typing import TypedDict, Annotated

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
    severity_level: str    # levels: "critical", "warning", "info"
    incident_ocuured_at: str     # utc timestamp in string
    raw_alert_payload: dict
    error_summary: str # given by triage node
    current_status: str # ["triaged","investigating","awaiting_approval","mitigating","resolved","failed_mitigation"]
    root_cause: str # given by log & metric investigator node
    diagnostics: dict # {"app_logs":[...], "db_logs":[...]}
    is_resolved: bool
    mitigation_plan: list[dict]
    final_report: str # in markdown format