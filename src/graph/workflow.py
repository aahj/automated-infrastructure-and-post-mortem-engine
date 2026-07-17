import os
from pathlib import Path
from enum import Enum
import sqlite3

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.sqlite import SqliteSaver
from agents.triage_commander import triage_node
from graph.state import AgentState


class NodeName(Enum):
    TRIAGE_COMMANDER = "triage_commander"
    LOG_INVESTIGATOR = "log_investigator"
    MITIGATION_ENGINEER = "mitigation_engineer"
    POST_MORTEM = "post_mortem_scribe"
    HUMAN_APPROVAL = "human_approval"


def route_after_approval(state: dict) -> str:
    if state.get("approved", False):
        return NodeName.MITIGATION_ENGINEER.value
    return "end"


def route_after_mitigation(state: dict) -> str:
    if state.get("is_resolved", False):
        return NodeName.POST_MORTEM.value
    return NodeName.LOG_INVESTIGATOR.value


def build_graph(db_path: str = "data/checkpoints.db", interrupt_before: list | None = None):
    Path("data").mkdir(exist_ok=True)
    db_path = os.getenv("CHECKPOINT_DB_PATH", db_path)

    builder = StateGraph(AgentState)

    # register nodes
    builder.add_node(NodeName.TRIAGE_COMMANDER.value, triage_node)
    # builder.add_node(NodeName.LOG_INVESTIGATOR.value, log_investigator_node)
    # builder.add_node(NodeName.HUMAN_APPROVAL.value, human_approval_node)
    # builder.add_node(NodeName.MITIGATION_ENGINEER.value, mitigation_engineer_node)
    # builder.add_node(NodeName.POST_MORTEM.value, post_mortem_scribe_node)

    # static edges
    builder.add_edge(START, NodeName.TRIAGE_COMMANDER.value)
    builder.add_edge(NodeName.TRIAGE_COMMANDER.value, NodeName.LOG_INVESTIGATOR.value)
    builder.add_edge(NodeName.LOG_INVESTIGATOR.value, NodeName.HUMAN_APPROVAL.value)
    builder.add_edge(NodeName.POST_MORTEM.value, END)

    # dynamic edges
    builder.add_conditional_edges(
        NodeName.HUMAN_APPROVAL.value,
        route_after_approval,
        {NodeName.MITIGATION_ENGINEER.value: NodeName.MITIGATION_ENGINEER.value, "end": END},
    )

    builder.add_conditional_edges(
        NodeName.MITIGATION_ENGINEER.value,
        route_after_mitigation,
        {
            NodeName.POST_MORTEM.value: NodeName.POST_MORTEM.value,
            NodeName.LOG_INVESTIGATOR.value: NodeName.LOG_INVESTIGATOR.value,
        },
    )
    
    # IMPORTANT: create the connection directly, not via context manager.
    # SqliteSaver.from_conn_string() returns a context manager. If you use
    # `with SqliteSaver.from_conn_string(...) as checkpointer:`, the connection
    # closes when the `with` block exits. The graph object lives longer than
    # build_graph(), so the connection must stay open for the process lifetime.

    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    return builder.compile(checkpointer, interrupt_before=interrupt_before)

graph = build_graph()