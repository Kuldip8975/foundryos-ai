"""Aggregates all versioned API routers."""

from fastapi import APIRouter

from app.api.routes import admin, auth, health
from app.api.routes.analytics import analytics_router
from app.api.routes.master_data import (
    defect_categories_router,
    machines_router,
    products_router,
)
from app.api.routes.operations import downtime_router, maintenance_router
from app.api.routes.production import inspections_router, production_router
from app.api.routes.shift_reports import analysis_router, reports_router
from app.api.routes.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(machines_router)
api_router.include_router(products_router)
api_router.include_router(defect_categories_router)
api_router.include_router(production_router)
api_router.include_router(inspections_router)
api_router.include_router(downtime_router)
api_router.include_router(maintenance_router)
api_router.include_router(analytics_router)
api_router.include_router(analysis_router)
api_router.include_router(reports_router)
api_router.include_router(workflows_router)