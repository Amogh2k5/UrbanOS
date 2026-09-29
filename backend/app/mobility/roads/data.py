"""Roads data models, LTA API clients, and storage for road infrastructure data."""

from __future__ import annotations

import logging
import os
import csv
import json
import httpx
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager

import pandas as pd
from pydantic import BaseModel, Field
from typing import Literal

from backend.app.mobility.traffic.geo_zones import get_zone

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_DB_PATH = Path("data/roads_observations.db")
_DEFAULT_CSV_PATH = Path("data/roads/road_works_openings.csv")
_TAXI_STANDS_CSV = Path("data/roads/taxi_stands.csv")
_ROAD_SPEED_CSV = Path("data/roads/road_speeds.csv")

LTA_BASE_URL = "https://datamall2.mytransport.sg/ltaodataservice"
ROAD_WORKS_ENDPOINT = "/RoadWorks"
ROAD_OPENINGS_ENDPOINT = "/RoadOpenings"
TAXI_STANDS_ENDPOINT = "/TaxiStands"
ROAD_SPEED_BANDS_ENDPOINT = "/v4/TrafficSpeedBands"
TIMEOUT = 15.0
PAGE_SIZE = 500


def _get_lta_api_key() -> str:
    """Get LTA API key from environment (lazy load)."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("LTA_API_KEY")
    if not api_key:
        raise ValueError("LTA_API_KEY not configured")
    return api_key

# -----------------------------------------------------------------------------
# Pydantic models for road infrastructure data
# -----------------------------------------------------------------------------

class RoadWork(BaseModel):
    """LTA Road Work event."""
    event_id: str
    start_date: str
    end_date: str
    svc_dept: str
    road_name: str
    other: str
    
    # Derived fields
    is_active: bool = False
    is_upcoming: bool = False
    days_until_start: Optional[int] = None
    days_until_end: Optional[int] = None


class RoadOpening(BaseModel):
    """LTA Road Opening event."""
    event_id: str
    start_date: str
    end_date: str
    svc_dept: str
    road_name: str
    other: str
    
    # Derived fields
    is_active: bool = False
    is_upcoming: bool = False
    days_until_start: Optional[int] = None
    days_until_end: Optional[int] = None


class TaxiStand(BaseModel):
    """LTA Taxi Stand with geographic coordinates."""
    taxi_code: str
    latitude: float
    longitude: float
    bfa: str
    ownership: str
    type: str
    name: str
    
    # Derived
    is_bfa_accessible: bool = False


class RoadWorkEvent(BaseModel):
    """Unified road work/opening event for unified display."""
    event_id: str
    event_type: Literal["road_work", "road_opening"]
    road_name: str
    start_date: str
    end_date: str
    svc_dept: str
    description: str
    status: Literal["active", "upcoming", "completed"]


class TaxiStandInfo(BaseModel):
    """Taxi stand information for display."""
    taxi_code: str
    name: str
    latitude: float
    longitude: float
    bfa: str
    ownership: str
    type: str
    is_bfa_accessible: bool = False


class RoadSpeedBand(BaseModel):
    """Traffic speed band for a road link."""
    link_id: str
    road_name: str
    road_category: str
    speed_band: int
    minimum_speed: Optional[float]
    maximum_speed: Optional[float]
    speed_midpoint: float
    start_latitude: Optional[float]
    start_longitude: Optional[float]
    end_latitude: Optional[float]
    end_longitude: Optional[float]
    zone_id: Optional[str]
    zone_name: Optional[str]
    observed_at: str
    speed_midpoint: float


class RoadSegmentSpeed(BaseModel):
    """Road segment with current speed and speed band."""
    link_id: str
    road_name: str
    road_category: str
    current_speed: float
    speed_band: int
    speed_midpoint: float
    zone_id: Optional[str]
    zone_name: Optional[str]
    observed_at: str


# -----------------------------------------------------------------------------
# LTA API Clients
# -----------------------------------------------------------------------------

class RoadWorksApiClient:
    """Client for LTA RoadWorks API."""
    
    def __init__(
        self,
        base_url: str = "https://datamall2.mytransport.sg/ltaodataservice",
        api_key: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or _get_lta_api_key()
        self.timeout = timeout
    
    def fetch_page(self, skip: int = 0, top: int = 500) -> Dict[str, Any]:
        """Fetch a single page of road works."""
        url = f"https://datamall2.mytransport.sg/ltaodataservice/RoadWorks"
        params = {"$top": 500, "$skip": skip}
        headers = {"AccountKey": self.api_key, "accept": "application/json"}
        
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=headers, params=params, timeout=15.0)
            resp.raise_for_status()
            return resp.json()
    
    def fetch_all(self):
        """Fetch all pages of road works as an async generator."""
        skip = 0
        page_size = 500
        headers = {"AccountKey": self.api_key, "accept": "application/json"}
        
        while True:
            url = f"https://datamall2.mytransport.sg/ltaodataservice/RoadWorks?$top=500&$skip={skip}"
            resp = httpx.get(url, headers=headers, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            value = data.get("value", [])
            if not value:
                break
            yield from value
            if len(value) < 500:
                break
            skip += page_size


class RoadOpeningsApiClient:
    """Client for LTA RoadOpenings API."""
    
    def __init__(
        self,
        base_url: str = "https://datamall2.mytransport.sg/ltaodataservice",
        api_key: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or _get_lta_api_key()
        self.timeout = timeout
    
    def fetch_all(self):
        """Fetch all road openings with pagination as an async generator."""
        skip = 0
        page_size = 500
        headers = {"AccountKey": self.api_key, "accept": "application/json"}
        
        while True:
            url = f"https://datamall2.mytransport.sg/ltaodataservice/RoadOpenings?$top=500&$skip={skip}"
            resp = httpx.get(url, headers=headers, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            value = data.get("value", [])
            if not value:
                break
            yield from value
            if len(value) < 500:
                break
            skip += page_size


class TaxiStandsApiClient:
    """Client for LTA TaxiStands API."""
    
    def __init__(
        self,
        base_url: str = "https://datamall2.mytransport.sg/ltaodataservice",
        api_key: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or _get_lta_api_key()
        self.timeout = timeout
    
    def fetch(self) -> List[Dict]:
        """Fetch all taxi stands."""
        url = f"{self.base_url}/TaxiStands"
        headers = {"AccountKey": self.api_key, "accept": "application/json"}
        resp = httpx.get(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        return data.get("value", [])


# -----------------------------------------------------------------------------
# Data Processing & Storage
# -----------------------------------------------------------------------------

class RoadDataProcessor:
    """Processes raw LTA API data into structured road infrastructure models."""
    
    @staticmethod
    def process_road_works(raw_data: List[Dict]) -> List[RoadWork]:
        """Process raw RoadWorks data into RoadWork models."""
        road_works = []
        now = datetime.now()
        
        for item in raw_data:
            try:
                start_date = parse_datetime(item.get("StartDate", ""))
                end_date = parse_datetime(item.get("EndDate", ""))
                
                now = datetime.now()
                is_active = start_date <= now <= end_date if start_date and end_date else False
                is_upcoming = start_date > now if start_date else False
                
                days_until_start = (start_date - now).days if start_date and start_date > now else None
                days_until_end = (end_date - now).days if end_date and end_date > now else None
                
                road_work = RoadWork(
                    event_id=item.get("EventID", ""),
                    start_date=item.get("StartDate", ""),
                    end_date=item.get("EndDate", ""),
                    svc_dept=item.get("SvcDept", ""),
                    road_name=item.get("RoadName", ""),
                    other=item.get("Other", ""),
                    is_active=is_active,
                    is_upcoming=is_upcoming,
                    days_until_start=days_until_start,
                    days_until_end=days_until_end,
                )
                road_works.append(road_work)
            except Exception as e:
                log.warning(f"Failed to process road work item: {e}")
                continue
        
        return road_works
    
    @staticmethod
    def process_road_openings(raw_data: List[Dict]) -> List[RoadOpening]:
        """Process raw RoadOpenings data into RoadOpening models."""
        openings = []
        now = datetime.now()
        
        for item in raw_data:
            try:
                start_date = parse_datetime(item.get("StartDate", ""))
                end_date = parse_datetime(item.get("EndDate", ""))
                
                is_active = start_date <= now <= end_date if start_date and end_date else False
                is_upcoming = start_date > now if start_date else False
                
                days_until_start = (start_date - datetime.now()).days if start_date and start_date > datetime.now() else None
                days_until_end = (end_date - datetime.now()).days if end_date and end_date > datetime.now() else None
                
                opening = RoadOpening(
                    event_id=item.get("EventID", ""),
                    start_date=item.get("StartDate", ""),
                    end_date=item.get("EndDate", ""),
                    svc_dept=item.get("SvcDept", ""),
                    road_name=item.get("RoadName", ""),
                    other=item.get("Other", ""),
                    is_active=is_active,
                    is_upcoming=is_upcoming,
                    days_until_start=days_until_start,
                    days_until_end=days_until_end,
                )
                openings.append(opening)
            except Exception as e:
                log.warning(f"Failed to process road opening item: {e}")
                continue
        
        return openings
    
    @staticmethod
    def process_taxi_stands(raw_data: List[Dict]) -> List[TaxiStand]:
        """Process raw TaxiStands data into TaxiStand models."""
        taxi_stands = []
        
        for item in raw_data:
            try:
                lat = float(item.get("Latitude", 0))
                lon = float(item.get("Longitude", 0))
                bfa = item.get("Bfa", "")
                is_bfa = bfa.lower() == "yes" if bfa else False
                
                stand = TaxiStand(
                    taxi_code=item.get("TaxiCode", ""),
                    latitude=lat,
                    longitude=lon,
                    bfa=item.get("Bfa", ""),
                    ownership=item.get("Ownership", ""),
                    type=item.get("Type", ""),
                    name=item.get("Name", ""),
                    is_bfa_accessible=is_bfa,
                )
                taxi_stands.append(stand)
            except Exception as e:
                log.warning(f"Failed to process taxi stand: {e}")
                continue
        
        return taxi_stands


def parse_datetime(date_str: str) -> Optional[datetime]:
    """Parse various datetime formats from LTA API."""
    if not date_str:
        return None
    try:
        # Try ISO format first
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        try:
            # Try common LTA format
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            try:
                return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None


# -----------------------------------------------------------------------------
# CSV Export for Prediction Cache
# -----------------------------------------------------------------------------

class RoadsCSVExporter:
    """Export road data to CSV for prediction cache."""
    
    @staticmethod
    def export_road_works(road_works: List[RoadWork], csv_path: Path) -> None:
        """Export road works to CSV."""
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "event_id", "start_date", "end_date", "svc_dept", "road_name", "other",
                "is_active", "is_upcoming", "days_until_start", "days_until_end"
            ])
            writer.writeheader()
            for rw in road_works:
                writer.writerow({
                    "event_id": rw.event_id,
                    "start_date": rw.start_date,
                    "end_date": rw.end_date,
                    "svc_dept": rw.svc_dept,
                    "road_name": rw.road_name,
                    "other": rw.other,
                    "is_active": rw.is_active,
                    "is_upcoming": rw.is_upcoming,
                    "days_until_start": rw.days_until_start,
                    "days_until_end": rw.days_until_end,
                })
    
    @staticmethod
    def export_road_openings(openings: List[RoadOpening], csv_path: Path) -> None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "event_id", "start_date", "end_date", "svc_dept", "road_name", "other",
                "is_active", "is_upcoming", "days_until_start", "days_until_end"
            ])
            writer.writeheader()
            for op in openings:
                writer.writerow({
                    "event_id": op.event_id,
                    "start_date": op.start_date,
                    "end_date": op.end_date,
                    "svc_dept": op.svc_dept,
                    "road_name": op.road_name,
                    "other": op.other,
                    "is_active": op.is_active,
                    "is_upcoming": op.is_upcoming,
                    "days_until_start": op.days_until_start,
                    "days_until_end": op.days_until_end,
                })
    
    @staticmethod
    def export_taxi_stands(taxi_stands: List[TaxiStand], csv_path: Path) -> None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "taxi_code", "latitude", "longitude", "bfa", "ownership", "type", "name", "is_bfa_accessible"
            ])
            writer.writeheader()
            for ts in taxi_stands:
                writer.writerow({
                    "taxi_code": ts.taxi_code,
                    "latitude": ts.latitude,
                    "longitude": ts.longitude,
                    "bfa": ts.bfa,
                    "ownership": ts.ownership,
                    "type": ts.type,
                    "name": ts.name,
                    "is_bfa_accessible": ts.is_bfa_accessible,
                })

# Re-export for convenience
from backend.app.mobility.traffic.geo_zones import get_zone

__all__ = [
    "RoadWork",
    "RoadOpening", 
    "TaxiStand",
    "RoadWorkEvent",
    "TaxiStandInfo",
    "RoadSpeedBand",
    "RoadSegmentSpeed",
    "RoadWorksApiClient",
    "RoadOpeningsApiClient",
    "TaxiStandsApiClient",
    "RoadDataProcessor",
    "RoadsCSVExporter",
    "parse_datetime",
]