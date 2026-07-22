from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agents.log_investigator import get_log_investigator_tools, log_investigator_node
from agents.triage_commander import triage_node
from constants import NodeName
from graph.state import AgentState


def route_after_approval(state: dict) -> str:
    if state.get("approved", False):
        return NodeName.MITIGATION_ENGINEER.value
    return "end"


def route_after_mitigation(state: dict) -> str:
    if state.get("is_resolved", False):
        return NodeName.POST_MORTEM.value
    return NodeName.LOG_INVESTIGATOR.value


async def build_graph(checkpointer: AsyncPostgresSaver, interrupt_before: list | None = None):

    builder = StateGraph(AgentState)
    log_investigator_tools = await get_log_investigator_tools()

    # register nodes
    builder.add_node(NodeName.TRIAGE_COMMANDER.value, triage_node)
    builder.add_node(NodeName.LOG_INVESTIGATOR.value, log_investigator_node)
    builder.add_node(NodeName.LOG_INVESTIGATOR_TOOL.value, ToolNode(log_investigator_tools))
    # builder.add_node(NodeName.HUMAN_APPROVAL.value, human_approval_node)
    # builder.add_node(NodeName.MITIGATION_ENGINEER.value, mitigation_engineer_node)
    # builder.add_node(NodeName.POST_MORTEM.value, post_mortem_scribe_node)

    # static edges
    builder.add_edge(START, NodeName.TRIAGE_COMMANDER.value)
    builder.add_edge(NodeName.TRIAGE_COMMANDER.value, NodeName.LOG_INVESTIGATOR.value)

    # builder.add_edge(
    #     NodeName.LOG_INVESTIGATOR.value, END
    # )  # TODO: remove this edge when other nodes are implemented

    # Re-Act Loop: Tool Node MUST route back to the investigator to evaluate tool outputs
    builder.add_edge(NodeName.LOG_INVESTIGATOR_TOOL.value, NodeName.LOG_INVESTIGATOR.value)
    # builder.add_edge(NodeName.POST_MORTEM.value, END)

    # dynamic edges

    # Conditional Edge: Investigator decides to call tools AGAIN or proceed to Approval
    builder.add_conditional_edges(
        NodeName.LOG_INVESTIGATOR.value,
        tools_condition,
        {
            "tools": NodeName.LOG_INVESTIGATOR_TOOL.value,
            #  "__end__": NodeName.HUMAN_APPROVAL.value
            "__end__": END,  # TODO: remove this
        },
    )
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

    return builder.compile(checkpointer, interrupt_before=interrupt_before)
