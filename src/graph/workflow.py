from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agents.evidence_synthesizer import evidence_synthesizer_node
from agents.human_approval import human_approval_node
from agents.log_investigator import get_log_investigator_tools, log_investigator_node
from agents.triage_commander import triage_node
from constants import MAX_TOOL_ITERATION, NodeName
from graph.state import AgentState, increment_tool_iterations


def route_after_approval(state: dict) -> str:
    if state.get("approved", False):
        # return NodeName.MITIGATION_ENGINEER.value
        return "end"  # TODO: remove this when other nodes completed
    return "end"


def route_after_mitigation(state: dict) -> str:
    if state.get("is_resolved", False):
        return NodeName.POST_MORTEM.value
    return NodeName.LOG_INVESTIGATOR.value


def investigator_router(state: dict) -> str:
    last_message = state["messages"][-1]
    current_tool_iterations = state.get("tool_iterations", 0)

    if current_tool_iterations >= MAX_TOOL_ITERATION:
        print(
            "[CIRCUIT BREAKER] "
            f"Terminating the tool iteration. Reached {current_tool_iterations} iteration(s)"
        )
        return "__end__"

    if getattr(last_message, "tool_calls", None):
        return "tools"

    return "__end__"


async def build_graph(checkpointer: AsyncPostgresSaver, interrupt_before: list | None = None):

    builder = StateGraph(AgentState)
    log_investigator_tools = await get_log_investigator_tools()

    ### REGISTER NODES
    builder.add_node(NodeName.TRIAGE_COMMANDER.value, triage_node)
    builder.add_node(NodeName.LOG_INVESTIGATOR.value, log_investigator_node)
    builder.add_node(NodeName.EVIDENCE_SYNTHESIZER.value, evidence_synthesizer_node)
    builder.add_node(NodeName.LOG_INVESTIGATOR_TOOL.value, ToolNode(log_investigator_tools))
    builder.add_node(NodeName.INCREMENT_TOOL_COUNTER.value, increment_tool_iterations)

    builder.add_node(NodeName.HUMAN_APPROVAL.value, human_approval_node)
    # builder.add_node(NodeName.MITIGATION_ENGINEER.value, mitigation_engineer_node)
    # builder.add_node(NodeName.POST_MORTEM.value, post_mortem_scribe_node)

    ### STATIC EDGES
    builder.add_edge(START, NodeName.TRIAGE_COMMANDER.value)
    builder.add_edge(NodeName.TRIAGE_COMMANDER.value, NodeName.LOG_INVESTIGATOR.value)

    # ReAct Loop: Investigator Tool Node must increment the tool iterations
    # and then route back to the Investigator Node to evaluate the tool output
    builder.add_edge(NodeName.LOG_INVESTIGATOR_TOOL.value, NodeName.INCREMENT_TOOL_COUNTER.value)
    builder.add_edge(NodeName.INCREMENT_TOOL_COUNTER.value, NodeName.LOG_INVESTIGATOR.value)
    builder.add_edge(NodeName.EVIDENCE_SYNTHESIZER.value, NodeName.HUMAN_APPROVAL.value)

    # builder.add_edge(NodeName.POST_MORTEM.value, END)

    ### DYNAMIC EDGES

    # Conditional Edge: Investigator decides to call tools AGAIN or proceed to Approval
    builder.add_conditional_edges(
        NodeName.LOG_INVESTIGATOR.value,
        investigator_router,
        {
            "tools": NodeName.LOG_INVESTIGATOR_TOOL.value,
            "__end__": NodeName.EVIDENCE_SYNTHESIZER.value,
        },
    )

    builder.add_conditional_edges(
        NodeName.HUMAN_APPROVAL.value,
        route_after_approval,
        {NodeName.MITIGATION_ENGINEER.value: NodeName.MITIGATION_ENGINEER.value, "end": END},
    )

    # builder.add_conditional_edges(
    #     NodeName.MITIGATION_ENGINEER.value,
    #     route_after_mitigation,
    #     {
    #         NodeName.POST_MORTEM.value: NodeName.POST_MORTEM.value,
    #         NodeName.LOG_INVESTIGATOR.value: NodeName.LOG_INVESTIGATOR.value,
    #     },
    # )

    return builder.compile(checkpointer, interrupt_before=interrupt_before)
