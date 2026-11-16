from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from agents.human_approval import human_approval_node
from agents.log_investigator import log_investigator_node
from agents.mitigation_engineer import mitigation_engineer_node
from agents.mitigation_executor import (
    mitigation_executor_node,
)
from agents.triage_commander import triage_node
from constants import NodeName
from graph.state import AgentState


def route_after_approval(state: dict) -> str:
    if state.get("approved", False):
        return NodeName.MITIGATION_EXECUTOR.value
    return "end"


def route_after_mitigation(state: dict) -> str:
    if state.get("is_resolved", False):
        # TODO: The post-mortem node is not implemented yet; finish after verified recovery.
        # return NodeName.POST_MORTEM.value
        return "end"
    return NodeName.LOG_INVESTIGATOR.value


async def build_graph(checkpointer: AsyncPostgresSaver, interrupt_before: list | None = None):

    builder = StateGraph(AgentState)

    ### REGISTER NODES
    builder.add_node(NodeName.TRIAGE_COMMANDER.value, triage_node)
    builder.add_node(NodeName.LOG_INVESTIGATOR.value, log_investigator_node)
    builder.add_node(NodeName.HUMAN_APPROVAL.value, human_approval_node)
    builder.add_node(NodeName.MITIGATION_EXECUTOR.value, mitigation_executor_node)
    builder.add_node(NodeName.MITIGATION_ENGINEER.value, mitigation_engineer_node)
    # builder.add_node(NodeName.POST_MORTEM.value, post_mortem_scribe_node)

    ### STATIC EDGES
    builder.add_edge(START, NodeName.TRIAGE_COMMANDER.value)
    builder.add_edge(NodeName.TRIAGE_COMMANDER.value, NodeName.LOG_INVESTIGATOR.value)
    builder.add_edge(NodeName.LOG_INVESTIGATOR.value, NodeName.HUMAN_APPROVAL.value)
    builder.add_edge(NodeName.MITIGATION_EXECUTOR.value, NodeName.MITIGATION_ENGINEER.value)

    # builder.add_edge(NodeName.POST_MORTEM.value, END)

    ### DYNAMIC EDGES

    builder.add_conditional_edges(
        NodeName.HUMAN_APPROVAL.value,
        route_after_approval,
        {NodeName.MITIGATION_EXECUTOR.value: NodeName.MITIGATION_EXECUTOR.value, "end": END},
    )

    builder.add_conditional_edges(
        NodeName.MITIGATION_ENGINEER.value,
        route_after_mitigation,
        {
            # NodeName.POST_MORTEM.value: NodeName.POST_MORTEM.value,
            "end": END,
            NodeName.LOG_INVESTIGATOR.value: NodeName.LOG_INVESTIGATOR.value,
        },
    )

    return builder.compile(checkpointer, interrupt_before=interrupt_before)
