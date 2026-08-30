from enum import Enum


class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"
    AUTO_MITIGATION_APPROVED = "auto_mitigation_approved"
    MANUAL_MITIGATION_REQUIRED = "manual_mitigation_required"


class NodeName(Enum):
    TRIAGE_COMMANDER = "triage_commander"
    LOG_INVESTIGATOR = "log_investigator"
    MITIGATION_EXECUTOR = "mitigation_executor"
    MITIGATION_ENGINEER = "mitigation_engineer"
    POST_MORTEM = "post_mortem_scribe"
    HUMAN_APPROVAL = "human_approval"


class Agents(Enum):
    LOG_INVESTIGATOR = "log_investigator"
    MITIGATION_EXECUTOR = "mitigation_executor"
    MITIGATION_ENGINEER = "mitigation_engineer"


CONNECTION_ESTABLISH_COOL_DOWN_PERIOD_SEC = 5
MAX_CONCURRENT_JOBS = 3
MAX_EXECUTOR_TOOL_ROUNDS = 5
MAX_ENGINEER_TOOL_ROUNDS = 5
MAX_INVESTIGATOR_TOOL_ROUNDS = 5

MUTATING_OPERATION_REGEX = (
    r"\b(delete|drop|insert|kill|post|put|patch|reload|restart|terminate|truncate|update|write)\b"
)
