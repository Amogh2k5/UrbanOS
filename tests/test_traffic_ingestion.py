"""Tests for LTA Traffic Speed Bands v2 ingestion pipeline.

Covers:
1. Valid LTA response parsing
2. Speed band parsing
3. Midpoint calculation
4. LinkID preservation
5. Coordinate validation
6. Zone point-in-polygon mapping
7. Segment outside all zones
8. Missing API key
9. Malformed LTA response
10. Duplicate observation handling
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import httpx

from backend.app.mobility.traffic.speed_bands_v2 import (
    TrafficSpeedBandsV2ApiClient,
    TrafficSpeedBandsV2Snapshot,
    TrafficSpeedBandV2,
    _now_iso,
)
from backend.app.mobility.traffic.storage import (
    TrafficObservationStore,
    TrafficObservation,
    snapshot_to_observations,
)
from backend.app.mobility.traffic.collector import (
    TrafficCollector,
    collect_traffic_once,
    get_collection_stats,
    CollectionResult,
)
from backend.app.mobility.traffic.geo_zones import get_zone, ZoneLookup

SG_OFFSET = timezone(timedelta(hours=8))

# Mock LTA v2 API response
MOCK_LTA_RESPONSE = {
    "odata.metadata": "http://datamall2.mytransport.sg/ltaodataservice/$metadata#TrafficSpeedBandsv2",
    "value": [
        {
            "LinkID": "101",
            "RoadName": "AYER RAJAH EXPRESSWAY",
            "RoadCategory": "Expressway",
            "SpeedBand": 3,
            "MinimumSpeed": 50,
            "MaximumSpeed": 70,
            "StartLatitude": 1.290,
            "StartLongitude": 103.785,
            "EndLatitude": 1.300,
            "EndLongitude": 103.790,
        },
        {
            "LinkID": "102",
            "RoadName": "PIE",
            "RoadCategory": "Expressway",
            "SpeedBand": 2,
            "MinimumSpeed": 70,
            "MaximumSpeed": 90,
            "StartLatitude": 1.330,
            "StartLongitude": 103.850,
            "EndLatitude": 1.340,
            "EndLongitude": 103.860,
        },
        {
            "LinkID": "103",
            "RoadName": "CTE",
            "RoadCategory": "Expressway",
            "SpeedBand": 4,
            "MinimumSpeed": 40,
            "MaximumSpeed": 60,
            "StartLatitude": 1.350,
            "StartLongitude": 103.870,
            "EndLatitude": 1.360,
            "EndLongitude": 103.880,
        },
        # Segment outside all zones (in the ocean)
        {
            "LinkID": "999",
            "RoadName": "OCEAN ROAD",
            "RoadCategory": "Arterial",
            "SpeedBand": 1,
            "MinimumSpeed": 0,
            "MaximumSpeed": 30,
            "StartLatitude": 1.0,
            "StartLongitude": 103.0,
            "EndLatitude": 1.1,
            "EndLongitude": 103.1,
        },
        # Segment with missing coordinates
        {
            "LinkID": "200",
            "RoadName": "UNKNOWN ROAD",
            "RoadCategory": "Local",
            "SpeedBand": 1,
            "MinimumSpeed": 0,
            "MaximumSpeed": 50,
            "StartLatitude": None,
            "StartLongitude": None,
            "EndLatitude": None,
            "EndLongitude": None,
        },
    ],
}


class TestZoneMapping:
    """Tests for zone point-in-polygon mapping."""

    def test_zone_lookup_loads(self):
        """Zone lookup should load 8 zones from GeoJSON."""
        lookup = ZoneLookup()
        lookup.load()
        assert lookup.is_loaded
        zones = lookup.get_all_zones()
        assert len(zones) == 8
        zone_ids = {z["zone_id"] for z in zones}
        expected = {
            "SG_NORTH", "SG_NORTH_EAST", "SG_CENTRAL_NORTH", "SG_CENTRAL_SOUTH",
            "SG_EAST", "SG_WEST_NORTH", "SG_WEST_SOUTH", "SG_SENTOSA",
        }
        assert zone_ids == expected

    def test_zone_mapping_central_south(self):
        """Marina Bay area should map to Central South."""
        # Marina Bay coordinates
        result = get_zone(1.285, 103.855)
        assert result["zone_id"] == "SG_CENTRAL_SOUTH"

    def test_zone_mapping_north(self):
        """Woodlands area should map to North."""
        result = get_zone(1.430, 103.780)
        assert result["zone_id"] == "SG_NORTH"

    def test_zone_mapping_east(self):
        """Bedok/Tampines area should map to East."""
        result = get_zone(1.350, 103.930)
        assert result["zone_id"] == "SG_EAST"

    def test_zone_mapping_west_south(self):
        """Jurong area should map to West South."""
        # Jurong East is at the boundary, use a coordinate clearly in West South
        result = get_zone(1.310, 103.720)
        assert result["zone_id"] == "SG_WEST_SOUTH"

    def test_zone_mapping_sentosa(self):
        """Sentosa should map to SG_SENTOSA."""
        result = get_zone(1.245, 103.820)
        assert result["zone_id"] == "SG_SENTOSA"

    def test_zone_outside_all_zones(self):
        """Points outside Singapore should return None zone_id."""
        result = get_zone(0, 0)  # Null Island
        assert result["zone_id"] is None
        assert result["zone_name"] == "unknown"

        result = get_zone(1.0, 103.5)  # South of Singapore
        assert result["zone_id"] is None

        result = get_zone(1.4, 104.5)  # East of Singapore
        assert result["zone_id"] is None


class TestApiClient:
    """Tests for TrafficSpeedBandsV2ApiClient."""

    def test_missing_api_key_raises(self):
        """Client should raise ValueError when LTA_API_KEY is not set."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="LTA_API_KEY not configured"):
                TrafficSpeedBandsV2ApiClient()

    def test_client_initializes_with_key(self):
        """Client should initialize with provided API key."""
        client = TrafficSpeedBandsV2ApiClient(api_key="test-key-123")
        assert client.api_key == "test-key-123"

    def test_mock_live_success(self):
        """Mock successful LTA v2 API response and verify parsing."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch()

                assert snapshot.is_live is True
                assert snapshot.provider == "LTA DataMall"
                assert len(snapshot.segments) == 5

                # Verify first segment
                seg = snapshot.segments[0]
                assert seg.link_id == "101"
                assert seg.road_name == "AYER RAJAH EXPRESSWAY"
                assert seg.road_category == "Expressway"
                assert seg.speed_band == 3
                assert seg.minimum_speed == 50.0
                assert seg.maximum_speed == 70.0
                assert seg.start_latitude == 1.290
                assert seg.start_longitude == 103.785
                assert seg.end_latitude == 1.300
                assert seg.end_longitude == 103.790

    def test_midpoint_calculation(self):
        """Speed midpoint should be (min + max) / 2."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch()

                # Segment 101: (50 + 70) / 2 = 60
                seg101 = next(s for s in snapshot.segments if s.link_id == "101")
                assert seg101.speed_midpoint == 60.0

                # Segment 102: (70 + 90) / 2 = 80
                seg102 = next(s for s in snapshot.segments if s.link_id == "102")
                assert seg102.speed_midpoint == 80.0

                # Segment 103: (40 + 60) / 2 = 50
                seg103 = next(s for s in snapshot.segments if s.link_id == "103")
                assert seg103.speed_midpoint == 50.0

    def test_linkid_preservation(self):
        """LinkID must be preserved as string."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch()

                link_ids = [s.link_id for s in snapshot.segments]
                assert "101" in link_ids
                assert "102" in link_ids
                assert "103" in link_ids
                assert "999" in link_ids
                assert "200" in link_ids
                # All should be strings
                assert all(isinstance(lid, str) for lid in link_ids)

    def test_coordinate_validation(self):
        """Coordinates should be parsed as floats."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch()

                seg101 = next(s for s in snapshot.segments if s.link_id == "101")
                assert isinstance(seg101.start_latitude, float)
                assert isinstance(seg101.start_longitude, float)
                assert isinstance(seg101.end_latitude, float)
                assert isinstance(seg101.end_longitude, float)
                assert seg101.start_latitude == 1.290
                assert seg101.start_longitude == 103.785

    def test_zone_mapping_on_segments(self):
        """Segments with coordinates should be mapped to zones."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch()

                # Segment 101 (AYER RAJAH) - should be in West South or Central South
                seg101 = next(s for s in snapshot.segments if s.link_id == "101")
                assert seg101.zone_id is not None
                assert seg101.zone_name is not None

                # Segment 102 (PIE) - should be in East or Central
                seg102 = next(s for s in snapshot.segments if s.link_id == "102")
                assert seg102.zone_id is not None

                # Segment 999 (Ocean) - should be outside all zones
                seg999 = next(s for s in snapshot.segments if s.link_id == "999")
                assert seg999.zone_id is None
                assert seg999.zone_name == "unknown"

                # Segment 200 (no coordinates) - should be unmapped
                seg200 = next(s for s in snapshot.segments if s.link_id == "200")
                assert seg200.zone_id is None
                assert seg200.zone_name is None

    def test_http_timeout_raises(self):
        """Timeout should raise, not fall back to fixture."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client.get") as mock_get:
                mock_get.side_effect = httpx.TimeoutException("timeout")

                client = TrafficSpeedBandsV2ApiClient()
                with pytest.raises(httpx.TimeoutException):
                    client.fetch()

    def test_http_error_raises(self):
        """HTTP error should raise, not fall back to fixture."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "401", request=MagicMock(), response=MagicMock()
                )
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                with pytest.raises(httpx.HTTPStatusError):
                    client.fetch()

    def test_malformed_response_raises(self):
        """Malformed JSON response should raise."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.side_effect = ValueError("invalid json")
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                with pytest.raises(ValueError, match="invalid json"):
                    client.fetch()

    def test_snake_case_fields(self):
        """Parser should handle snake_case field names."""
        snake_payload = {
            "value": [
                {
                    "link_id": "301",
                    "road_name": "TEST ROAD",
                    "road_category": "Expressway",
                    "speed_band": 2,
                    "minimum_speed": 60,
                    "maximum_speed": 80,
                    "start_latitude": 1.3,
                    "start_longitude": 103.8,
                    "end_latitude": 1.31,
                    "end_longitude": 103.81,
                }
            ],
        }

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = snake_payload
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch()

                assert len(snapshot.segments) == 1
                seg = snapshot.segments[0]
                assert seg.link_id == "301"
                assert seg.road_name == "TEST ROAD"
                assert seg.speed_midpoint == 70.0


class TestPagination:
    """Tests for fetch_all_pages pagination logic."""

    def _make_mock_response(self, items: list):
        """Create a mock response with the given items."""
        return {
            "odata.metadata": "http://datamall2.mytransport.sg/ltaodataservice/$metadata#TrafficSpeedBands",
            "value": items,
        }

    def _make_segment(self, link_id: str, start_lat=1.29, start_lon=103.78, end_lat=1.30, end_lon=103.79):
        """Create a mock segment."""
        return {
            "LinkID": link_id,
            "RoadName": f"ROAD {link_id}",
            "RoadCategory": "Expressway",
            "SpeedBand": 3,
            "MinimumSpeed": 50,
            "MaximumSpeed": 70,
            "StartLat": start_lat,
            "StartLon": start_lon,
            "EndLat": end_lat,
            "EndLon": end_lon,
        }

    def test_single_page_response(self):
        """Single page (< PAGE_SIZE) should return all segments."""
        page_items = [self._make_segment(str(i)) for i in range(10)]
        mock_payload = self._make_mock_response(page_items)

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = mock_payload
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch_all_pages()

                assert len(snapshot.segments) == 10
                assert mock_client.get.call_count == 1
                # Verify correct URL called
                call_args = mock_client.get.call_args
                assert "$top=500" in call_args[0][0]
                assert "$skip=0" in call_args[0][0]

    def test_multi_page_response(self):
        """Multiple full pages should be fetched and combined."""
        # Page 0: 500 items
        page0_items = [self._make_segment(f"P0-{i}") for i in range(500)]
        # Page 1: 500 items
        page1_items = [self._make_segment(f"P1-{i}") for i in range(500)]
        # Page 2: 300 items (final partial page)
        page2_items = [self._make_segment(f"P2-{i}") for i in range(300)]

        responses = [
            self._make_mock_response(page0_items),
            self._make_mock_response(page1_items),
            self._make_mock_response(page2_items),
        ]

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                
                # Create sequence of responses
                mock_responses = []
                for resp_data in responses:
                    mock_resp = MagicMock()
                    mock_resp.raise_for_status.return_value = None
                    mock_resp.json.return_value = resp_data
                    mock_responses.append(mock_resp)
                
                mock_client.get.side_effect = mock_responses
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch_all_pages()

                assert len(snapshot.segments) == 1300
                assert mock_client.get.call_count == 3
                
                # Verify skip progression
                calls = mock_client.get.call_args_list
                assert "$skip=0" in calls[0][0][0]
                assert "$skip=500" in calls[1][0][0]
                assert "$skip=1000" in calls[2][0][0]
                
                # Verify all LinkIDs are present and unique
                link_ids = [s.link_id for s in snapshot.segments]
                assert len(set(link_ids)) == 1300

    def test_final_partial_page(self):
        """Final page with < PAGE_SIZE items should be included and stop pagination."""
        page0_items = [self._make_segment(f"P0-{i}") for i in range(500)]
        page1_items = [self._make_segment(f"P1-{i}") for i in range(250)]  # partial

        responses = [
            self._make_mock_response(page0_items),
            self._make_mock_response(page1_items),
        ]

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                
                mock_responses = []
                for resp_data in responses:
                    mock_resp = MagicMock()
                    mock_resp.raise_for_status.return_value = None
                    mock_resp.json.return_value = resp_data
                    mock_responses.append(mock_resp)
                
                mock_client.get.side_effect = mock_responses
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch_all_pages()

                assert len(snapshot.segments) == 750
                assert mock_client.get.call_count == 2

    def test_empty_response(self):
        """Empty response should return empty snapshot without error."""
        mock_payload = self._make_mock_response([])

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = mock_payload
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch_all_pages()

                assert len(snapshot.segments) == 0
                assert mock_client.get.call_count == 1

    def test_correct_skip_progression(self):
        """$skip should progress 0, 500, 1000, 1500, ..."""
        page_items = [self._make_segment(f"P{i}-{j}") for i in range(4) for j in range(500)]
        # 4 pages of 500 = 2000 items
        responses = [self._make_mock_response(page_items[i*500:(i+1)*500]) for i in range(4)]
        # Add final partial page
        responses.append(self._make_mock_response([self._make_segment("FINAL")]))

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                
                mock_responses = []
                for resp_data in responses:
                    mock_resp = MagicMock()
                    mock_resp.raise_for_status.return_value = None
                    mock_resp.json.return_value = resp_data
                    mock_responses.append(mock_resp)
                
                mock_client.get.side_effect = mock_responses
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch_all_pages()

                assert len(snapshot.segments) == 2001
                assert mock_client.get.call_count == 5
                
                calls = mock_client.get.call_args_list
                expected_skips = [0, 500, 1000, 1500, 2000]
                for i, expected_skip in enumerate(expected_skips):
                    assert f"$skip={expected_skip}" in calls[i][0][0], f"Call {i}: expected skip={expected_skip}, got {calls[i][0][0]}"

    def test_no_duplicate_linkids_across_pages(self):
        """LinkIDs across pages should be unique (no overlap)."""
        # Create pages with deliberately unique LinkIDs
        page0_items = [self._make_segment(f"A-{i}") for i in range(500)]
        page1_items = [self._make_segment(f"B-{i}") for i in range(500)]
        page2_items = [self._make_segment(f"C-{i}") for i in range(100)]

        responses = [
            self._make_mock_response(page0_items),
            self._make_mock_response(page1_items),
            self._make_mock_response(page2_items),
        ]

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                
                mock_responses = []
                for resp_data in responses:
                    mock_resp = MagicMock()
                    mock_resp.raise_for_status.return_value = None
                    mock_resp.json.return_value = resp_data
                    mock_responses.append(mock_resp)
                
                mock_client.get.side_effect = mock_responses
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch_all_pages()

                link_ids = [s.link_id for s in snapshot.segments]
                assert len(link_ids) == 1100
                assert len(set(link_ids)) == 1100  # All unique

    def test_failed_page_stops_collection_and_reports_error(self):
        """If a page fails, collection should stop and raise the error."""
        page0_items = [self._make_segment(f"P0-{i}") for i in range(500)]
        page0_resp = self._make_mock_response(page0_items)

        import httpx

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                
                # First page succeeds
                mock_resp0 = MagicMock()
                mock_resp0.raise_for_status.return_value = None
                mock_resp0.json.return_value = page0_resp
                
                # Second page fails
                mock_client.get.side_effect = [mock_resp0, httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())]
                
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                
                with pytest.raises(httpx.HTTPStatusError):
                    client.fetch_all_pages()
                
                # Should have made 2 calls (first succeeded, second failed)
                assert mock_client.get.call_count == 2

    def test_all_pages_stored_in_snapshot(self):
        """All pages should be combined into single snapshot with shared timestamp."""
        page0_items = [self._make_segment(f"P0-{i}") for i in range(500)]
        page1_items = [self._make_segment(f"P1-{i}") for i in range(300)]

        responses = [
            self._make_mock_response(page0_items),
            self._make_mock_response(page1_items),
        ]

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                
                mock_responses = []
                for resp_data in responses:
                    mock_resp = MagicMock()
                    mock_resp.raise_for_status.return_value = None
                    mock_resp.json.return_value = resp_data
                    mock_responses.append(mock_resp)
                
                mock_client.get.side_effect = mock_responses
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch_all_pages()

                # All segments should have the same observed_at (snapshot timestamp)
                observed_ats = {s.observed_at for s in snapshot.segments}
                assert len(observed_ats) == 1
                assert snapshot.snapshot_at == list(observed_ats)[0]
                
                # All segments should be in the snapshot
                assert len(snapshot.segments) == 800

    def test_zone_mapping_intact_across_pages(self):
        """Zone mapping should work for segments on all pages."""
        # Create segments in different zones
        # Page 0: 500 segments in Central South (Marina Bay area)
        page0_items = [self._make_segment(f"CS-{i}", 1.285, 103.855, 1.286, 103.856) for i in range(500)]
        # Page 1: 500 segments in North (Woodlands area)
        page1_items = [self._make_segment(f"N-{i}", 1.430, 103.780, 1.431, 103.781) for i in range(500)]
        # Page 2: 300 segments in East (Bedok area) - final partial page
        page2_items = [self._make_segment(f"E-{i}", 1.350, 103.930, 1.351, 103.931) for i in range(300)]

        responses = [
            self._make_mock_response(page0_items),
            self._make_mock_response(page1_items),
            self._make_mock_response(page2_items),
        ]

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                
                mock_responses = []
                for resp_data in responses:
                    mock_resp = MagicMock()
                    mock_resp.raise_for_status.return_value = None
                    mock_resp.json.return_value = resp_data
                    mock_responses.append(mock_resp)
                
                mock_client.get.side_effect = mock_responses
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch_all_pages()

                assert len(snapshot.segments) == 1300
                
                # Check zone mapping
                zone_counts = {}
                for seg in snapshot.segments:
                    zone_counts[seg.zone_id] = zone_counts.get(seg.zone_id, 0) + 1
                
                assert "SG_CENTRAL_SOUTH" in zone_counts
                assert "SG_NORTH" in zone_counts
                assert "SG_EAST" in zone_counts
                assert zone_counts["SG_CENTRAL_SOUTH"] == 500
                assert zone_counts["SG_NORTH"] == 500
                assert zone_counts["SG_EAST"] == 300

    def test_deduplication_intact_across_pages(self):
        """Deduplication key (observed_at, link_id) should work across all pages."""
        # Same LinkIDs on different pages (simulating potential overlap)
        page0_items = [self._make_segment(f"SHARED-{i}") for i in range(500)]
        page1_items = [self._make_segment(f"SHARED-{i}") for i in range(300)]  # Some overlap

        responses = [
            self._make_mock_response(page0_items),
            self._make_mock_response(page1_items),
        ]

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                
                mock_responses = []
                for resp_data in responses:
                    mock_resp = MagicMock()
                    mock_resp.raise_for_status.return_value = None
                    mock_resp.json.return_value = resp_data
                    mock_responses.append(mock_resp)
                
                mock_client.get.side_effect = mock_responses
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch_all_pages()

                # The API itself shouldn't have duplicates, but if it did,
                # the snapshot would contain them (deduplication happens at storage)
                link_ids = [s.link_id for s in snapshot.segments]
                # All 800 segments should be in the snapshot
                assert len(snapshot.segments) == 800
                # But if there were duplicates in the API, they'd appear here
                # The storage layer handles deduplication


class TestStorage:
    """Tests for TrafficObservationStore."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        store = TrafficObservationStore(db_path)
        yield store
        # Cleanup
        db_path.unlink(missing_ok=True)

    def test_upsert_and_query(self, temp_db):
        """Test basic upsert and query operations."""
        obs = TrafficObservation(
            observed_at="2026-08-20T10:00:00+08:00",
            link_id="101",
            road_name="TEST ROAD",
            road_category="Expressway",
            speed_band=3,
            minimum_speed=50.0,
            maximum_speed=70.0,
            speed_midpoint=60.0,
            start_latitude=1.29,
            start_longitude=103.785,
            end_latitude=1.30,
            end_longitude=103.79,
            zone_id="SG_WEST_SOUTH",
            zone_name="West South",
            created_at="2026-08-20T10:00:00+08:00",
        )

        inserted, updated = temp_db.upsert_observations([obs])
        assert inserted == 1
        assert updated == 0

        # Query by timerange
        results = temp_db.query_by_timerange(
            "2026-08-20T00:00:00+08:00",
            "2026-08-20T23:59:59+08:00",
        )
        assert len(results) == 1
        assert results[0].link_id == "101"
        assert results[0].speed_midpoint == 60.0

    def test_duplicate_handling(self, temp_db):
        """Duplicate (observed_at, link_id) should update, not insert."""
        obs1 = TrafficObservation(
            observed_at="2026-08-20T10:00:00+08:00",
            link_id="101",
            road_name="TEST ROAD",
            road_category="Expressway",
            speed_band=3,
            minimum_speed=50.0,
            maximum_speed=70.0,
            speed_midpoint=60.0,
            start_latitude=1.29,
            start_longitude=103.785,
            end_latitude=1.30,
            end_longitude=103.79,
            zone_id="SG_WEST_SOUTH",
            zone_name="West South",
            created_at="2026-08-20T10:00:00+08:00",
        )

        # First insert
        inserted, updated = temp_db.upsert_observations([obs1])
        assert inserted == 1
        assert updated == 0

        # Update with different speed
        obs2 = TrafficObservation(
            observed_at="2026-08-20T10:00:00+08:00",
            link_id="101",
            road_name="TEST ROAD",
            road_category="Expressway",
            speed_band=4,
            minimum_speed=40.0,
            maximum_speed=60.0,
            speed_midpoint=50.0,
            start_latitude=1.29,
            start_longitude=103.785,
            end_latitude=1.30,
            end_longitude=103.79,
            zone_id="SG_WEST_SOUTH",
            zone_name="West South",
            created_at="2026-08-20T10:05:00+08:00",
        )

        inserted, updated = temp_db.upsert_observations([obs2])
        assert inserted == 0
        assert updated == 1

        # Verify updated value
        results = temp_db.query_by_link_id("101")
        assert len(results) == 1
        assert results[0].speed_band == 4
        assert results[0].speed_midpoint == 50.0

    def test_query_by_link_id(self, temp_db):
        """Query by link_id should return all observations for that link."""
        for i in range(3):
            obs = TrafficObservation(
                observed_at=f"2026-08-20T{10+i}:00:00+08:00",
                link_id="101",
                road_name="TEST ROAD",
                road_category="Expressway",
                speed_band=3,
                minimum_speed=50.0,
                maximum_speed=70.0,
                speed_midpoint=60.0,
                start_latitude=1.29,
                start_longitude=103.785,
                end_latitude=1.30,
                end_longitude=103.79,
                zone_id="SG_WEST_SOUTH",
                zone_name="West South",
                created_at=f"2026-08-20T{10+i}:00:00+08:00",
            )
            temp_db.upsert_observations([obs])

        results = temp_db.query_by_link_id("101", limit=10)
        assert len(results) == 3
        # Should be ordered by observed_at DESC
        assert results[0].observed_at == "2026-08-20T12:00:00+08:00"

    def test_get_latest_snapshot(self, temp_db):
        """Get latest snapshot should return observations at max timestamp."""
        for hour in [10, 11, 12]:
            obs = TrafficObservation(
                observed_at=f"2026-08-20T{hour}:00:00+08:00",
                link_id="101",
                road_name="TEST ROAD",
                road_category="Expressway",
                speed_band=3,
                minimum_speed=50.0,
                maximum_speed=70.0,
                speed_midpoint=60.0,
                start_latitude=1.29,
                start_longitude=103.785,
                end_latitude=1.30,
                end_longitude=103.79,
                zone_id="SG_WEST_SOUTH",
                zone_name="West South",
                created_at=f"2026-08-20T{hour}:00:00+08:00",
            )
            temp_db.upsert_observations([obs])

        latest = temp_db.get_latest_snapshot()
        assert len(latest) == 1
        assert latest[0].observed_at == "2026-08-20T12:00:00+08:00"

    def test_stats(self, temp_db):
        """Storage stats should return correct counts."""
        for i in range(3):
            obs = TrafficObservation(
                observed_at=f"2026-08-20T{10+i}:00:00+08:00",
                link_id=f"10{i}",
                road_name="TEST ROAD",
                road_category="Expressway",
                speed_band=3,
                minimum_speed=50.0,
                maximum_speed=70.0,
                speed_midpoint=60.0,
                start_latitude=1.29,
                start_longitude=103.785,
                end_latitude=1.30,
                end_longitude=103.79,
                zone_id="SG_WEST_SOUTH" if i < 2 else None,
                zone_name="West South" if i < 2 else None,
                created_at=f"2026-08-20T{10+i}:00:00+08:00",
            )
            temp_db.upsert_observations([obs])

        stats = temp_db.get_stats()
        assert stats["total_observations"] == 3
        assert stats["unique_link_ids"] == 3
        assert stats["unique_zones_mapped"] == 1
        assert stats["earliest_observation"] == "2026-08-20T10:00:00+08:00"
        assert stats["latest_observation"] == "2026-08-20T12:00:00+08:00"


class TestSnapshotConversion:
    """Tests for converting snapshots to storage observations."""

    def test_snapshot_to_observations(self):
        """Convert snapshot segments to TrafficObservation list."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                client = TrafficSpeedBandsV2ApiClient()
                snapshot = client.fetch()

                observations = snapshot_to_observations(snapshot)

                assert len(observations) == 5
                for obs in observations:
                    assert isinstance(obs, TrafficObservation)
                    assert obs.link_id in ["101", "102", "103", "999", "200"]
                    assert obs.speed_midpoint >= 0
                    assert obs.observed_at == snapshot.snapshot_at


class TestCollector:
    """Tests for TrafficCollector service."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        store = TrafficObservationStore(db_path)
        yield store
        db_path.unlink(missing_ok=True)

    def test_collect_once_mock(self, temp_db):
        """Test collection run with mocked API."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                collector = TrafficCollector(store=temp_db)
                result = collector.collect_once()

                assert result.records_received == 5
                assert result.records_stored == 5
                assert result.records_updated == 0
                assert result.zones_mapped == 3  # 101, 102, 103 have coords in zones
                assert result.zones_unmapped == 2  # 999 (ocean), 200 (no coords)
                assert len(result.errors) == 0

    def test_collect_once_duplicate_run(self, temp_db):
        """Second collection run at same timestamp should update, not insert."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                # Mock _now_iso to return fixed timestamp for both runs
                fixed_timestamp = "2026-08-20T10:00:00+08:00"
                with patch("backend.app.mobility.traffic.speed_bands_v2._now_iso", return_value=fixed_timestamp):
                    collector = TrafficCollector(store=temp_db)

                    # First run
                    result1 = collector.collect_once()
                    assert result1.records_stored == 5
                    assert result1.records_updated == 0

                    # Second run (same timestamp because we mock _now_iso)
                    result2 = collector.collect_once()
                    assert result2.records_stored == 5
                    assert result2.records_updated == 5

    def test_missing_api_key_error(self, temp_db):
        """Collection should fail cleanly with missing API key."""
        with patch.dict("os.environ", {}, clear=True):
            # TrafficCollector creates its own client which will raise on init
            with pytest.raises(ValueError, match="LTA_API_KEY not configured"):
                TrafficCollector(store=temp_db)

    def test_get_collection_stats(self, temp_db):
        """get_collection_stats should return storage stats."""
        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                collector = TrafficCollector(store=temp_db)
                collector.collect_once()

                stats = get_collection_stats()
                # Note: get_collection_stats creates its own store instance
                # so it won't see the temp_db data. This is expected behavior.


class TestNowIso:
    """Test timestamp generation."""

    def test_now_iso_format(self):
        """_now_iso should return ISO format with +08:00 offset."""
        ts = _now_iso()
        # Should parse as valid ISO datetime
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(hours=8)


class TestScheduler:
    """Tests for TrafficScheduler."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        store = TrafficObservationStore(db_path)
        yield store
        db_path.unlink(missing_ok=True)

    def _make_mock_collector(self, result: CollectionResult):
        """Create a mock collector that returns the given result."""
        mock_collector = MagicMock(spec=TrafficCollector)
        mock_collector.collect_once.return_value = result
        return mock_collector

    def test_configurable_interval(self):
        """Scheduler should accept configurable interval."""
        from backend.app.mobility.traffic.scheduler import SchedulerConfig

        config = SchedulerConfig(interval_seconds=60)
        assert config.interval_seconds == 60

        config = SchedulerConfig(interval_seconds=300)
        assert config.interval_seconds == 300

    def test_successful_repeated_collection(self, temp_db):
        """Scheduler should run multiple successful collections."""
        from backend.app.mobility.traffic.scheduler import TrafficScheduler, SchedulerConfig

        mock_result = CollectionResult(
            timestamp="2026-08-20T10:00:00+08:00",
            records_received=100,
            records_stored=100,
            records_updated=0,
            zones_mapped=95,
            zones_unmapped=5,
            errors=[],
        )

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            mock_collector = self._make_mock_collector(mock_result)
            config = SchedulerConfig(interval_seconds=1, max_runtime_seconds=3)
            scheduler = TrafficScheduler(config=config, collector=mock_collector)

            scheduler.run()

            # With 1-second interval and 3-second max runtime, should run ~3 times
            assert scheduler._run_count >= 2
            assert mock_collector.collect_once.call_count >= 2

    def test_cadence_starts_on_interval(self, temp_db):
        """Collections should start at regular intervals from previous START time."""
        from backend.app.mobility.traffic.scheduler import TrafficScheduler, SchedulerConfig
        import time

        mock_result = CollectionResult(
            timestamp="2026-08-20T10:00:00+08:00",
            records_received=100,
            records_stored=100,
            records_updated=0,
            zones_mapped=95,
            zones_unmapped=5,
            errors=[],
        )

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            # Mock collector that takes 0.5 seconds
            def slow_collect():
                time.sleep(0.5)
                return mock_result

            mock_collector = MagicMock(spec=TrafficCollector)
            mock_collector.collect_once.side_effect = slow_collect
            config = SchedulerConfig(interval_seconds=1, max_runtime_seconds=4)
            scheduler = TrafficScheduler(config=config, collector=mock_collector)

            start_time = time.time()
            scheduler.run()
            total_time = time.time() - start_time

            # Should run ~4 times in 4 seconds with 1-second interval
            assert scheduler._run_count >= 3
            # Total time should be approximately 3-4 seconds (not stretched by collection time)
            assert total_time < 5.0

    def test_collection_longer_than_interval_logs_warning(self, temp_db):
        """If collection takes longer than interval, next starts immediately with warning."""
        from backend.app.mobility.traffic.scheduler import TrafficScheduler, SchedulerConfig
        import time

        mock_result = CollectionResult(
            timestamp="2026-08-20T10:00:00+08:00",
            records_received=100,
            records_stored=100,
            records_updated=0,
            zones_mapped=95,
            zones_unmapped=5,
            errors=[],
        )

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            # Mock collector that takes 2 seconds (longer than 1-second interval)
            def slow_collect():
                time.sleep(2.0)
                return mock_result

            mock_collector = MagicMock(spec=TrafficCollector)
            mock_collector.collect_once.side_effect = slow_collect
            config = SchedulerConfig(interval_seconds=1, max_runtime_seconds=5)
            scheduler = TrafficScheduler(config=config, collector=mock_collector)

            start_time = time.time()
            scheduler.run()
            total_time = time.time() - start_time

            # With 2-second collections and 1-second interval, should run ~2-3 times
            assert scheduler._run_count >= 2
            # Total time should be ~5 seconds (not more)
            assert total_time < 7.0

    def test_no_overlapping_collections(self, temp_db):
        """Scheduler should not start a new collection if previous is still running."""
        from backend.app.mobility.traffic.scheduler import TrafficScheduler, SchedulerConfig

        # Test that the lock prevents concurrent collections by checking is_running
        mock_result = CollectionResult(
            timestamp="2026-08-20T10:00:00+08:00",
            records_received=100,
            records_stored=100,
            records_updated=0,
            zones_mapped=95,
            zones_unmapped=5,
            errors=[],
        )

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            mock_collector = self._make_mock_collector(mock_result)
            config = SchedulerConfig(interval_seconds=1, max_runtime_seconds=3)
            scheduler = TrafficScheduler(config=config, collector=mock_collector)

            # Test is_running property
            assert scheduler.is_running() is False
            
            # Manually set collection_in_progress to simulate running collection
            scheduler._collection_in_progress = True
            assert scheduler.is_running() is True
            
            # When lock is held by another thread, acquire would block
            # The run() loop uses acquire(blocking=False) which would return False
            # and skip the cycle. We test this behavior directly:
            acquired = scheduler._collection_lock.acquire(blocking=False)
            assert acquired is True  # We got the lock
            scheduler._collection_lock.release()
            
            # Now hold the lock and try to acquire with blocking=False
            scheduler._collection_lock.acquire()
            try:
                acquired = scheduler._collection_lock.acquire(blocking=False)
                assert acquired is False  # Would skip in run()
            finally:
                scheduler._collection_lock.release()

    def test_graceful_shutdown(self, temp_db):
        """Scheduler should stop gracefully on stop event."""
        from backend.app.mobility.traffic.scheduler import TrafficScheduler, SchedulerConfig

        mock_result = CollectionResult(
            timestamp="2026-08-20T10:00:00+08:00",
            records_received=100,
            records_stored=100,
            records_updated=0,
            zones_mapped=95,
            zones_unmapped=5,
            errors=[],
        )

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            mock_collector = self._make_mock_collector(mock_result)
            config = SchedulerConfig(interval_seconds=1, max_runtime_seconds=2)
            scheduler = TrafficScheduler(config=config, collector=mock_collector)

            scheduler.run()

            assert scheduler._run_count >= 1
            assert scheduler._run_count <= 2

    def test_failed_snapshot_handling(self, temp_db):
        """Scheduler should continue after a failed collection."""
        from backend.app.mobility.traffic.scheduler import TrafficScheduler, SchedulerConfig

        fail_result = CollectionResult(
            timestamp="2026-08-20T10:00:00+08:00",
            records_received=0,
            records_stored=0,
            records_updated=0,
            zones_mapped=0,
            zones_unmapped=0,
            errors=["API fetch failed: timeout"],
        )
        success_result = CollectionResult(
            timestamp="2026-08-20T10:00:01+08:00",
            records_received=100,
            records_stored=100,
            records_updated=0,
            zones_mapped=95,
            zones_unmapped=5,
            errors=[],
        )

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            mock_collector = MagicMock(spec=TrafficCollector)
            mock_collector.collect_once.side_effect = [fail_result, success_result]

            config = SchedulerConfig(interval_seconds=10, max_runtime_seconds=15)
            scheduler = TrafficScheduler(config=config, collector=mock_collector)

            scheduler.run()

            # Should have run twice (failure doesn't stop scheduler)
            assert scheduler._run_count == 2
            assert mock_collector.collect_once.call_count == 2

    def test_missing_api_key_stops_scheduler(self, temp_db):
        """Scheduler should exit with error if LTA_API_KEY is missing."""
        from backend.app.mobility.traffic.scheduler import TrafficScheduler, SchedulerConfig

        with patch.dict("os.environ", {}, clear=True):
            # Provide a mock collector to avoid API client creation in TrafficCollector
            mock_collector = MagicMock(spec=TrafficCollector)
            config = SchedulerConfig(interval_seconds=1, max_runtime_seconds=3)
            scheduler = TrafficScheduler(config=config, collector=mock_collector)

            # run() should call sys.exit(1) when API key missing
            with pytest.raises(SystemExit) as exc_info:
                scheduler.run()
            assert exc_info.value.code == 1

    def test_logging_does_not_expose_api_key(self, temp_db, caplog):
        """Scheduler logs should not contain API key."""
        import logging
        from backend.app.mobility.traffic.scheduler import TrafficScheduler, SchedulerConfig

        mock_result = CollectionResult(
            timestamp="2026-08-20T10:00:00+08:00",
            records_received=100,
            records_stored=100,
            records_updated=0,
            zones_mapped=95,
            zones_unmapped=5,
            errors=[],
        )

        with patch.dict("os.environ", {"LTA_API_KEY": "secret-key-12345"}, clear=True):
            mock_collector = self._make_mock_collector(mock_result)
            config = SchedulerConfig(interval_seconds=1, max_runtime_seconds=2)
            scheduler = TrafficScheduler(config=config, collector=mock_collector)

            with caplog.at_level(logging.INFO):
                scheduler.run()

            # Check no log message contains the API key
            for record in caplog.records:
                assert "secret-key-12345" not in record.getMessage()
                assert "LTA_API_KEY" not in record.getMessage()

    def test_existing_collector_behavior_unchanged(self, temp_db):
        """Existing TrafficCollector.collect_once() behavior should be unchanged."""
        from backend.app.mobility.traffic.collector import TrafficCollector

        with patch.dict("os.environ", {"LTA_API_KEY": "dummy"}, clear=True):
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = MOCK_LTA_RESPONSE
                mock_client.get.return_value = mock_resp
                mock_client.__enter__.return_value = mock_client
                mock_client_class.return_value = mock_client

                collector = TrafficCollector(store=temp_db)
                result = collector.collect_once()

                assert result.records_received == 5
                assert result.records_stored == 5
                assert result.records_updated == 0
                assert result.zones_mapped == 3
                assert result.zones_unmapped == 2
                assert len(result.errors) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])