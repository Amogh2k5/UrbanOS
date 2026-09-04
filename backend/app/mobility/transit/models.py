"""Transit Pydantic models for API responses."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class BusServiceResponse(BaseModel):
    service_no: str
    operator: str
    direction: int
    category: str
    origin_code: str
    destination_code: str
    am_peak_freq: Optional[str] = None
    am_offpeak_freq: Optional[str] = None
    pm_peak_freq: Optional[str] = None
    pm_offpeak_freq: Optional[str] = None
    loop_desc: Optional[str] = None


class BusRouteResponse(BaseModel):
    service_no: str
    operator: str
    direction: int
    stop_sequence: int
    bus_stop_code: str
    distance: Optional[float] = None
    wd_first_bus: Optional[str] = None
    wd_last_bus: Optional[str] = None
    sat_first_bus: Optional[str] = None
    sat_last_bus: Optional[str] = None
    sun_first_bus: Optional[str] = None
    sun_last_bus: Optional[str] = None


class BusStopResponse(BaseModel):
    bus_stop_code: str
    road_name: str
    description: str
    latitude: float
    longitude: float


class TrainAlertResponse(BaseModel):
    line: str
    direction: Optional[str] = None
    station: Optional[str] = None
    message: str
    status: Optional[str] = None


class TransitStatusResponse(BaseModel):
    """Overall transit system status."""
    generated_at: datetime
    bus_services_count: int
    bus_routes_count: int
    bus_stops_count: int
    active_train_alerts: int
    train_alerts: List[TrainAlertResponse] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class BusArrivalRequest(BaseModel):
    """Request for bus arrival information (for future BusArrivalv2 integration)."""
    bus_stop_code: str
    service_no: Optional[str] = None


class BusArrivalResponse(BaseModel):
    """Bus arrival estimate (placeholder for future BusArrivalv2)."""
    bus_stop_code: str
    service_no: str
    operator: str
    next_bus: Optional[dict] = None
    subsequent_bus: Optional[dict] = None
    note: str = "BusArrivalv2 API not available with current LTA account"