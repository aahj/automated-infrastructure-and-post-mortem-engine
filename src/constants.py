from enum import Enum


class NodeName(Enum):
    TRIAGE_COMMANDER = "triage_commander"
    LOG_INVESTIGATOR = "log_investigator"
    EVIDENCE_SYNTHESIZER = "evidence_synthesizer"
    MITIGATION_ENGINEER = "mitigation_engineer"
    POST_MORTEM = "post_mortem_scribe"
    HUMAN_APPROVAL = "human_approval"
    # tools node
    LOG_INVESTIGATOR_TOOL = "log_investigator_tool"
    INCREMENT_TOOL_COUNTER = "increment_tool_counter"


class Agents(Enum):
    LOG_INVESTIGATOR = "log_investigator"
    MITIGATION_ENGINEER = "mitigation_engineer"


MAX_TOOL_ITERATION = 9
CONNECTION_ESTABLISH_COOL_DOWN_PERIOD_SEC = 5
MAX_CONCURRENT_JOBS = 3
