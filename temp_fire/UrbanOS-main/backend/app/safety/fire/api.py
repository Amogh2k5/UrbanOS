"""SCDF Fire incident and Singapore fire-statistics adapters.

Primary current source: SCDF public "Latest Happenings" pages. These are
published incident reports, not an operational dispatch feed. The adapter
therefore reports the published-feed scope and never converts "no article" into
"zero real-world incidents".

Historical source: data.gov.sg "Fire Occurrences, Annual" dataset published
by SINGSTAT from SCDF data.
"""
from __future__ import annotations

import hashlib
import html
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from backend.app.safety.fire.fire_rules import (
    classify_severity, classify_status, classify_type, infer_region
)
from backend.app.safety.fire.models import FireHistoryPoint, FireIncident

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))

SCDF_LATEST_URL = "https://www.scdf.gov.sg/home/about-scdf/media-room/latest-happenings"
FIRE_STATS_RESOURCE = "d_808473a208220960f07a0b064ef16bde"


@dataclass
class FireSnapshot:
    generated_at: datetime
    incidents: List[FireIncident] = field(default_factory=list)
    historical: List[FireHistoryPoint] = field(default_factory=list)
    source_status: str = "unavailable"
    data_sources: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "incidents": [i.model_dump(mode="json") for i in self.incidents],
            "historical_fire_counts": [h.model_dump(mode="json") for h in self.historical],
            "source_status": self.source_status,
            "data_sources": self.data_sources,
            "limitations": self.limitations,
            "warnings": self.warnings,
            "errors": self.errors,
        }


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "a":
            d = dict(attrs)
            self._href = d.get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            text = " ".join(" ".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None
            self._text = []


def _parse_date(text: str) -> Optional[datetime]:
    patterns = (
        r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
        r"(\d{1,2})/(\d{1,2})/(\d{4})",
    )
    for p in patterns:
        m = re.search(p, text)
        if not m:
            continue
        try:
            if m.lastindex == 3 and m.group(2).isalpha():
                return datetime.strptime(" ".join(m.groups()), "%d %B %Y").replace(tzinfo=SG)
            return datetime.strptime("/".join(m.groups()), "%d/%m/%Y").replace(tzinfo=SG)
        except ValueError:
            continue
    return None


def _clean_text(raw: str) -> str:
    raw = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(html.unescape(raw).split())


def _extract_location(title: str, body: str) -> Optional[str]:
    # SCDF titles commonly encode the location after "at", "in", or "along".
    m = re.search(r"\b(?:at|in|along|near)\s+(.+)$", title, flags=re.I)
    if m:
        return m.group(1).strip(" .")
    m = re.search(r"\b(?:at|in|along)\s+(.{5,100}?)(?:\.|,?\s+SCDF\b)", body, flags=re.I)
    return m.group(1).strip(" .") if m else None


def _extract_affected_area(body: str) -> Optional[str]:
    patterns = (
        r"(?:affected area|area affected|size of the fire)[^.]{0,160}",
        r"(?:fire involved|fire involved an area)[^.]{0,160}",
    )
    for p in patterns:
        m = re.search(p, body, flags=re.I)
        if m:
            return m.group(0).strip()
    return None


class SCDFFireIncidentClient:
    """Fetch recent SCDF-published fire incident reports.

    The SCDF site is not an operational incident API. This client intentionally
    uses only public SCDF reports and exposes that limitation to callers.
    """

    def __init__(self, timeout_s: float = 15.0, max_articles: int = 12) -> None:
        self.timeout_s = timeout_s
        self.max_articles = max_articles

    def fetch(self) -> tuple[List[FireIncident], List[str], List[str], List[str]]:
        headers = {"User-Agent": "UrbanOS/1.0 (Fire Safety domain)"}
        errors: List[str] = []
        warnings = [
            "SCDF public incident reports are not a dispatch feed; published incidents are not guaranteed to be exhaustive or real-time."
        ]
        sources = [SCDF_LATEST_URL]
        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=True, headers=headers) as client:
                listing = client.get(SCDF_LATEST_URL)
                listing.raise_for_status()
                parser = _LinkParser()
                parser.feed(listing.text)

                candidates: List[tuple[str, str]] = []
                seen = set()
                for href, title in parser.links:
                    absolute = urljoin(SCDF_LATEST_URL, href)
                    low = f"{title} {absolute}".lower()
                    if "fire" not in low or absolute in seen:
                        continue
                    if "/latest-happenings/" not in absolute and "newsarticledetail" not in absolute:
                        continue
                    seen.add(absolute)
                    candidates.append((absolute, title))
                    if len(candidates) >= self.max_articles:
                        break

                incidents: List[FireIncident] = []
                for url, link_title in candidates:
                    try:
                        page = client.get(url)
                        page.raise_for_status()
                        body = _clean_text(page.text)
                        title = link_title or self._title_from_html(page.text) or "SCDF fire incident"
                        if "fire" not in f"{title} {body}".lower():
                            continue

                        published = _parse_date(body[:6000])
                        location = _extract_location(title, body)
                        status = classify_status(body)
                        severity = classify_severity(body)
                        incident_type = classify_type(title, body)
                        region = infer_region(location, None, None)
                        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
                        incidents.append(FireIncident(
                            id=f"SCDF-{digest}",
                            title=title,
                            source="SCDF public incident report",
                            source_url=url,
                            reported_at=published,
                            location=location,
                            incident_type=incident_type,
                            severity=severity,
                            status=status,
                            affected_area=_extract_affected_area(body),
                            region=region,
                            summary=body[:700] if body else None,
                            data_quality_flags=[
                                "published_report_not_operational_feed",
                                "coordinates_not_available_from_source",
                            ],
                        ))
                        sources.append(url)
                    except Exception as exc:
                        errors.append(f"SCDF article fetch failed for {url}: {exc}")
                return incidents, sources, warnings, errors
        except Exception as exc:
            errors.append(f"SCDF latest-happenings fetch failed: {exc}")
            return [], sources, warnings, errors

    @staticmethod
    def _title_from_html(page: str) -> Optional[str]:
        m = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.I | re.S)
        return _clean_text(m.group(1)) if m else None


class SingaporeFireStatisticsClient:
    """Fetch official annual fire counts from data.gov.sg."""

    def __init__(self, timeout_s: float = 15.0) -> None:
        self.timeout_s = timeout_s
        self.url = "https://data.gov.sg/api/action/datastore_search"

    def fetch(self) -> tuple[List[FireHistoryPoint], str, List[str]]:
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                r = client.get(self.url, params={"resource_id": FIRE_STATS_RESOURCE, "limit": 100})
                r.raise_for_status()
                payload = r.json()
            records = payload.get("result", {}).get("records", [])
            points: List[FireHistoryPoint] = []
            for row in records:
                series = str(row.get("DataSeries", "")).strip().lower()
                if "fire" not in series:
                    continue
                for key, value in row.items():
                    if re.fullmatch(r"\d{4}", str(key)) and value not in (None, ""):
                        try:
                            points.append(FireHistoryPoint(year=int(key), fires=int(float(value)), source=f"data.gov.sg:{FIRE_STATS_RESOURCE}"))
                        except (ValueError, TypeError):
                            pass
                break
            points.sort(key=lambda p: p.year)
            return points, f"data.gov.sg:{FIRE_STATS_RESOURCE}", []
        except Exception as exc:
            return [], f"data.gov.sg:{FIRE_STATS_RESOURCE}", [f"Historical fire statistics unavailable: {exc}"]


def fetch_fire_snapshot() -> FireSnapshot:
    now = datetime.now(SG)
    snapshot = FireSnapshot(generated_at=now)
    incident_client = SCDFFireIncidentClient(
        max_articles=int(os.getenv("URBANOS_FIRE_MAX_ARTICLES", "12"))
    )
    incidents, sources, warnings, errors = incident_client.fetch()
    snapshot.incidents = incidents
    snapshot.data_sources.extend(sources)
    snapshot.warnings.extend(warnings)
    snapshot.errors.extend(errors)

    stats, stats_source, stats_errors = SingaporeFireStatisticsClient().fetch()
    snapshot.historical = stats
    snapshot.data_sources.append(stats_source)
    snapshot.errors.extend(stats_errors)

    if incidents:
        snapshot.source_status = "published_incidents"
    elif errors and not stats:
        snapshot.source_status = "unavailable"
    else:
        snapshot.source_status = "historical_only"
    if not incidents:
        snapshot.limitations.append("No current SCDF-published fire incident records were retrieved; active-incident KPIs are therefore unavailable rather than zero.")
    snapshot.limitations.append("Annual fire statistics are historical aggregates and cannot establish current incident location, status, or severity.")
    return snapshot
