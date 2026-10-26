"""Enumerations stored as constrained strings (CHECK constraints, not native
PostgreSQL enums, so adding a value is a simple, reversible migration)."""

from __future__ import annotations

from enum import StrEnum


class DataSource(StrEnum):
    """Provenance of every row. ``synthetic`` rows are demo data, never real records."""

    MANUAL = "manual"
    IMPORT = "import"
    SYNTHETIC = "synthetic"


class DowntimeStatus(StrEnum):
    ONGOING = "ongoing"
    RESOLVED = "resolved"


class MaintenancePriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MaintenanceStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ReportStatus(StrEnum):
    """Lifecycle of an AI shift report (Module 3)."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


# --------------------------------------------------------------------------- Module 4


class WorkflowRole(StrEnum):
    """Roles for the workflow assistant. Permissions are fixed in backend code
    (app.services.workflow.permissions); the language model never decides them."""

    VIEWER = "viewer"  # ask read-only questions
    OPERATOR = "operator"  # + prepare maintenance requests for approval
    SUPERVISOR = "supervisor"  # + approve or reject proposed actions, see every session


# --------------------------------------------------------------------------- Module 5


class UserRole(StrEnum):
    """Roles of signed-in people. Permissions are fixed in backend code
    (app.core.permissions); a role sent by a browser is never trusted."""

    OPERATOR = "operator"  # production, quality and downtime for assigned machines
    SUPERVISOR = "supervisor"  # plant-wide views, report review, maintenance approval
    PRODUCTION_MANAGER = "production_manager"  # analytics and operational reporting
    ADMIN = "admin"  # user management, role assignment and access audit


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowStepStatus(StrEnum):
    OK = "ok"  # tool ran; its result is evidence
    REJECTED = "rejected"  # refused before running (not allowlisted, forbidden, bad arguments)
    ERROR = "error"  # ran but failed a business rule (e.g. unknown machine)


class ProposalStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    EXECUTED = "executed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


# Allowed status changes for maintenance requests. CLOSED and CANCELLED are terminal.
MAINTENANCE_TRANSITIONS: dict[MaintenanceStatus, frozenset[MaintenanceStatus]] = {
    MaintenanceStatus.OPEN: frozenset({MaintenanceStatus.IN_PROGRESS, MaintenanceStatus.CANCELLED}),
    MaintenanceStatus.IN_PROGRESS: frozenset(
        {MaintenanceStatus.OPEN, MaintenanceStatus.RESOLVED, MaintenanceStatus.CANCELLED}
    ),
    MaintenanceStatus.RESOLVED: frozenset(
        {MaintenanceStatus.CLOSED, MaintenanceStatus.IN_PROGRESS}
    ),
    MaintenanceStatus.CLOSED: frozenset(),
    MaintenanceStatus.CANCELLED: frozenset(),
}

# Statuses in which resolution details must be present.
MAINTENANCE_RESOLVED_STATUSES = frozenset({MaintenanceStatus.RESOLVED, MaintenanceStatus.CLOSED})


def sql_in_list(enum_cls: type[StrEnum]) -> str:
    """``'a', 'b'`` — the value list for a CHECK ... IN (...) constraint."""
    return ", ".join(f"'{member.value}'" for member in enum_cls)