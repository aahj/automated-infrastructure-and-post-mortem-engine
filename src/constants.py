from enum import Enum


class NodeName(Enum):
    TRIAGE_COMMANDER = "triage_commander"
    LOG_INVESTIGATOR = "log_investigator"
    MITIGATION_ENGINEER = "mitigation_engineer"
    POST_MORTEM = "post_mortem_scribe"
    HUMAN_APPROVAL = "human_approval"


class Agents(Enum):
    LOG_INVESTIGATOR = "log_investigator"
    MITIGATION_ENGINEER = "mitigation_engineer"
