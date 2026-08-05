from langgraph.types import interrupt


def human_approval_node(state: dict) -> dict:
    """
    LangGraph node: Human Approval
    Reads: state["root_cause"], state["service_name"], state["diagnostics"], state["severity_level"], state["incident_occurred_at"], state["error_summary"]
    Writes: state["approved"]: True if approved, False if rejected
                Also returns all other state keys explicitly
    """
    print(f"\n[Human Approval] Pausing for review...")

    incident_id = state["incident_id"]
    incident_occurred_at = state["incident_occurred_at"]
    severity_level = state["severity_level"]
    service_name = state["service_name"]
    error_summary = state["error_summary"]
    root_cause = state["root_cause"]
    diagnostics = state["diagnostics"]

    #     interrupt() pauses the execution
    #  the dict passes to the interrupt() is the payload. The caller reads this to know what to display to the user
    # Execution resumes when Command(resume=value) is called by the caller
    decision = interrupt(
        {
            "details": {
                "incident_id": incident_id,
                "incident_occurred_at": incident_occurred_at,
                "severity_level": severity_level,
                "service_name": service_name,
                "error_summary": error_summary,
                "root_cause": root_cause,
                "diagnostics": diagnostics,
            },
            "prompt": (
                "Does the above root cause and diagnostics look correct?\n"
                " Type 'yes' to approve, therefore agent can mitigate the issue\n"
                " Type 'no' to reject and leaving for manual investigation\n"
            ),
        }
    )

    approved = str(decision).lower().strip() in ("yes", "y", "approve")

    if approved:
        print(f"\n[Human Approval] Approved to mitigate the issue...\n")
    else:
        print(f"\n[Human Approval] Rejected and leaving for manual investigation...\n")

        # LangGraph 1.1.0: after Command(resume=...), the next node receives only
        # the keys returned by this node. Not the full pre-interrupt checkpoint.
        # Returning the complete state explicitly ensures downstream agents
        # receive complete state.

        return {
            "messages": state.get("messages", []),
            "session_id": state["session_id"],
            "incident_id": incident_id,
            "service_name": service_name,
            "severity_level": severity_level,
            "incident_occurred_at": incident_occurred_at,
            "raw_alert_payload": state["raw_alert_payload"],
            "error_summary": error_summary,
            "current_status": state["current_status"],
            "root_cause": root_cause,
            "diagnostics": diagnostics,
            "is_resolved": state["is_resolved"],
            "mitigation_plan": state["mitigation_plan"],
            "final_report": state["final_report"],
            "internal_error": None,
            "approved": approved,
            "tool_iterations": state["tool_iterations"],
        }
