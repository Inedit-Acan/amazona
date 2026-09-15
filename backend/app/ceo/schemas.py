from enum import StrEnum


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    MONITORING = "MONITORING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class DecisionStatus(StrEnum):
    GO = "GO"
    REVIEW = "REVIEW"
    NO_GO = "NO_GO"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
