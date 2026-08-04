def human_approval_node(state: dict) -> dict:
    """
    LangGraph node: Human Approval
    Reads: state["root_cause"], state["current_status"], state["diagnostics"]
    Writes: state["approved"]: True if approved, False if rejected
            Also returns all other state keys explicitly
    """
    