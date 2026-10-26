"""Role → permission mapping and data scope for signed-in users (Module 5).

This table is the single source of truth. It is fixed in backend code and
checked on every request; a role or permission sent by a browser is never
trusted. ``GET /auth/me`` reports a user's permissions so the web client can
hide controls the server would refuse anyway.

Data scope:
* operators only see and record data for machines assigned to them by an
  admin (production records, quality inspections, downtime, maintenance and
  the workflow assistant's tools);
* supervisors and production managers see the whole plant;
* admins manage accounts and read the access audit; they have no
  manufacturing-data permissions beyond the machine list needed to assign
  machines.
"""

from __future__ import annotations

from enum import StrEnum

from app.models.enums import UserRole, WorkflowRole


class Permission(StrEnum):
    MACHINES_READ = "machines:read"  # machines, products, defect categories
    MASTER_DATA_MANAGE = "master_data:manage"  # create/update machines, products, defects
    PRODUCTION_READ = "production:read"
    PRODUCTION_RECORD = "production:record"
    QUALITY_READ = "quality:read"
    QUALITY_RECORD = "quality:record"
    DOWNTIME_READ = "downtime:read"
    DOWNTIME_RECORD = "downtime:record"
    MAINTENANCE_READ = "maintenance:read"
    MAINTENANCE_MANAGE = "maintenance:manage"  # direct create/update (outside the assistant)
    ANALYTICS_READ = "analytics:read"  # plant dashboard and shift analysis
    REPORTS_READ = "reports:read"
    REPORTS_GENERATE = "reports:generate"
    ASSISTANT_USE = "assistant:use"
    ACTIONS_APPROVE = "actions:approve"  # approve/reject actions prepared by the assistant
    USERS_MANAGE = "users:manage"
    AUDIT_READ = "audit:read"


_OPERATOR = frozenset(
    {
        Permission.MACHINES_READ,
        Permission.PRODUCTION_READ,
        Permission.PRODUCTION_RECORD,
        Permission.QUALITY_READ,
        Permission.QUALITY_RECORD,
        Permission.DOWNTIME_READ,
        Permission.DOWNTIME_RECORD,
        Permission.MAINTENANCE_READ,
        Permission.ASSISTANT_USE,
    }
)

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.OPERATOR: _OPERATOR,
    UserRole.SUPERVISOR: _OPERATOR
    | {
        Permission.MAINTENANCE_MANAGE,
        Permission.ACTIONS_APPROVE,
        Permission.ANALYTICS_READ,
        Permission.REPORTS_READ,
        Permission.REPORTS_GENERATE,
    },
    UserRole.PRODUCTION_MANAGER: frozenset(
        {
            Permission.MACHINES_READ,
            Permission.MASTER_DATA_MANAGE,
            Permission.PRODUCTION_READ,
            Permission.QUALITY_READ,
            Permission.DOWNTIME_READ,
            Permission.MAINTENANCE_READ,
            Permission.ANALYTICS_READ,
            Permission.REPORTS_READ,
            Permission.REPORTS_GENERATE,
            Permission.ASSISTANT_USE,
        }
    ),
    UserRole.ADMIN: frozenset(
        {Permission.MACHINES_READ, Permission.USERS_MANAGE, Permission.AUDIT_READ}
    ),
}

# Roles whose manufacturing data is limited to their assigned machines.
MACHINE_SCOPED_ROLES = frozenset({UserRole.OPERATOR})

# How each role uses the Module 4 workflow assistant (whose own, unchanged
# permission table decides what each workflow role may do there):
# operators prepare maintenance requests, supervisors approve them,
# production managers ask read-only questions, admins have no access.
WORKFLOW_ROLE: dict[UserRole, WorkflowRole | None] = {
    UserRole.OPERATOR: WorkflowRole.OPERATOR,
    UserRole.SUPERVISOR: WorkflowRole.SUPERVISOR,
    UserRole.PRODUCTION_MANAGER: WorkflowRole.VIEWER,
    UserRole.ADMIN: None,
}

# Where the web client sends each role after signing in.
HOME_PAGE: dict[UserRole, str] = {
    UserRole.OPERATOR: "my-work",
    UserRole.SUPERVISOR: "dashboard",
    UserRole.PRODUCTION_MANAGER: "dashboard",
    UserRole.ADMIN: "admin",
}


def permissions_for(role: UserRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]