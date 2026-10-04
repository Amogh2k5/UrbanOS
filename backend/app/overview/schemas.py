"""Shared Pydantic schemas for UrbanOS Overview API.

These models are used by both the API endpoints and the context module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ModuleKPI(BaseModel):
    label: str
    value: Any
    unit: str


class ModuleSummary(BaseModel):
    id: str
    name: str
    status: str  # "normal" | "elevated" | "critical" | "unavailable"
    kpi: Optional[ModuleKPI] = None
    updated_at: Optional[str] = None
    detail_route: str


class AlertItem(BaseModel):
    domain: str
    severity: str
    title: str
    description: str
    timestamp: str
    affected_zones: List[str] = []


class CityOverviewResponse(BaseModel):
    generated_at: str
    modules: List[ModuleSummary]
    alerts: List[AlertItem]
    ai_brief: Optional[str] = None


class ModuleDetailResponse(BaseModel):
    module_id: str
    module_name: str
    status: str
    kpi: Optional[ModuleKPI] = None
    updated_at: Optional[str] = None
    summary: str
    alerts: List[AlertItem] = []
    cross_domain: List[str] = []
    detail_route: str


class ChatRequest(BaseModel):
    message: str
    module_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str