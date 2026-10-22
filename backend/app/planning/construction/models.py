"""ConstructionReport schema; source semantics and availability remain explicit."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class ConstructionSource(BaseModel):
    key: str
    name: str
    agency: str
    url: str
    status: str
    retrieved_at: str | None = None
    error: str | None = None
    record_count: int = 0
    fields: list[str] = Field(default_factory=list)
    total_count: int | None = None
    coverage_start: str | None = None
    coverage_end: str | None = None
    last_updated_at: str | None = None


class ConstructionInsight(BaseModel):
    question: str
    answer: str
    data_kind: str


class GreenMarkBuilding(BaseModel):
    vault_id: str | None = None
    reference_no: str | None = None
    project_name: str | None = None
    actual_project_name: str | None = None
    postal_code: str | None = None
    rating: str | None = None
    sle_ze_pe: str | None = None
    project_type: str | None = None
    gfa: str | None = None
    re_certification: str | None = None
    previous_gm_cert_reference_no: str | None = None
    gm_version: str | None = None
    e_cert: str | None = None
    expiry: str | None = None
    developer: str | None = None
    architect: str | None = None
    me_engineer: str | None = None
    cs_engineer: str | None = None
    facility_manager: str | None = None
    esd_consultant: str | None = None
    geometry: dict[str, Any] | None = None


class PipelineRecord(BaseModel):
    year: int | None = None
    provisional_permission: int | None = None
    written_permission: int | None = None
    building_plan_approval: int | None = None
    building_commencement: int | None = None
    building_completion: int | None = None


class ConstructionReport(BaseModel):
    generated_at: datetime
    domain: str = "planning"
    subdomain: str = "construction"
    status: str = "PARTIAL"
    kpis: dict[str, Any] = Field(default_factory=dict)
    greenmark_summary: dict[str, Any] = Field(default_factory=dict)
    pipeline_trend: list[dict[str, Any]] = Field(default_factory=list)
    greenmark_by_rating: list[dict[str, Any]] = Field(default_factory=list)
    greenmark_by_type: list[dict[str, Any]] = Field(default_factory=list)
    greenmark_buildings: list[GreenMarkBuilding] = Field(default_factory=list)
    pipeline_records: list[PipelineRecord] = Field(default_factory=list)
    map_data: dict[str, Any] = Field(default_factory=dict)
    sources: list[ConstructionSource] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    insights: list[ConstructionInsight] = Field(default_factory=list)
    confidence: str = "low"
    data_timestamps: dict[str, Any] = Field(default_factory=dict)
    is_ml_prediction: bool = False