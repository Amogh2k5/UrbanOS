"""Pydantic models for the Safety -> Crime domain."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CrimeSeries(BaseModel):
    name: str
    values: Dict[str, Optional[float]] = Field(default_factory=dict)
    unit: str = "cases"


class MajorOffenceSeries(CrimeSeries):
    pass


class ArrestSeries(BaseModel):
    offence: str
    values: Dict[str, Optional[float]] = Field(default_factory=dict)


class NpcCrimeSeries(BaseModel):
    npc: str
    offence: str
    values: Dict[str, Optional[float]] = Field(default_factory=dict)


class ScamType(BaseModel):
    name: str
    cases: Optional[int] = None
    loss_sgd_million: Optional[float] = None
    average_loss_sgd: Optional[float] = None


class CrimeReport(BaseModel):
    generated_at: datetime
    source_status: str = "unavailable"
    data_period: str = "unknown"
    data_sources: List[str] = Field(default_factory=list)

    total_physical_crime_2025: Optional[int] = None
    total_scams_cybercrime_2025: Optional[int] = None
    total_scams_2025: Optional[int] = None
    physical_crime_rate_2025: Optional[float] = None
    arrests_2025_total_selected_offences: Optional[int] = None

    overview: List[CrimeSeries] = Field(default_factory=list)
    major_offences: List[MajorOffenceSeries] = Field(default_factory=list)
    arrests: List[ArrestSeries] = Field(default_factory=list)
    npc_geography: List[NpcCrimeSeries] = Field(default_factory=list)
    scam_types: List[ScamType] = Field(default_factory=list)

    geographic_scope: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    is_ml_prediction: bool = False
