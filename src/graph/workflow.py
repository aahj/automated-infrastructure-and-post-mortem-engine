import os
from enum import Enum

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

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


async def build_graph(interrupt_before: list | None = None):

    builder = StateGraph(AgentState)

    # register nodes
    builder.add_node(NodeName.TRIAGE_COMMANDER.value, triage_node)
    # builder.add_node(NodeName.LOG_INVESTIGATOR.value, log_investigator_node)
    # builder.add_node(NodeName.HUMAN_APPROVAL.value, human_approval_node)
    # builder.add_node(NodeName.MITIGATION_ENGINEER.value, mitigation_engineer_node)
    # builder.add_node(NodeName.POST_MORTEM.value, post_mortem_scribe_node)

    # static edges
    builder.add_edge(START, NodeName.TRIAGE_COMMANDER.value)
    builder.add_edge(
        NodeName.TRIAGE_COMMANDER.value, END
    )  # TODO: remove this edge when other nodes are implemented

    # builder.add_edge(NodeName.TRIAGE_COMMANDER.value, NodeName.LOG_INVESTIGATOR.value)
    # builder.add_edge(NodeName.LOG_INVESTIGATOR.value, NodeName.HUMAN_APPROVAL.value)
    # builder.add_edge(NodeName.POST_MORTEM.value, END)

    # dynamic edges
    # builder.add_conditional_edges(
    #     NodeName.HUMAN_APPROVAL.value,
    #     route_after_approval,
    #     {NodeName.MITIGATION_ENGINEER.value: NodeName.MITIGATION_ENGINEER.value, "end": END},
    # )

    # builder.add_conditional_edges(
    #     NodeName.MITIGATION_ENGINEER.value,
    #     route_after_mitigation,
    #     {
    #         NodeName.POST_MORTEM.value: NodeName.POST_MORTEM.value,
    #         NodeName.LOG_INVESTIGATOR.value: NodeName.LOG_INVESTIGATOR.value,
    #     },
    # )

    # IMPORTANT: create the connection directly, not via context manager.
    # AsyncPostgresSaver.from_conn_string() returns a context manager. If you use
    # `with AsyncPostgresSaver.from_conn_string(...) as checkpointer:`, the connection
    # closes when the `with` block exits. The graph object lives longer than
    # build_graph(), so the connection must stay open for the process lifetime.

    pool = AsyncConnectionPool(
        conninfo=os.getenv("POSTGRES_CONNECTION_URI"),
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
        },
        max_size=10,
        open=False,  # open=False prevents it from connecting until we explicitly call .open()
    )
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)
    # Initialize checkpoint tables if they don't exist
    await checkpointer.setup()

    return builder.compile(checkpointer, interrupt_before=interrupt_before)
    # await pool.close()
