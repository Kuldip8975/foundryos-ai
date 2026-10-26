"""Model registry for Alembic.

Import every ORM model module here so ``Base.metadata`` is complete when
Alembic runs (and when tests build a schema).
"""

from app.db.base import Base
from app.models.auth import AuthAuditEvent, AuthSession, User, UserMachineAssignment
from app.models.manufacturing import (
    DefectCategory,
    Machine,
    MachineDowntimeEvent,
    MaintenanceRequest,
    Product,
    ProductionRecord,
    QualityInspection,
)
from app.models.reports import ShiftReport
from app.models.workflow import (
    ActionApproval,
    ActionProposal,
    WorkflowAuditEvent,
    WorkflowSession,
    WorkflowStep,
)

__all__ = [
    "ActionApproval",
    "ActionProposal",
    "AuthAuditEvent",
    "AuthSession",
    "Base",
    "DefectCategory",
    "Machine",
    "MachineDowntimeEvent",
    "MaintenanceRequest",
    "Product",
    "ProductionRecord",
    "QualityInspection",
    "ShiftReport",
    "User",
    "UserMachineAssignment",
    "WorkflowAuditEvent",
    "WorkflowSession",
    "WorkflowStep",
]