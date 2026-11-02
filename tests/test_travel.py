from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from school_finder import geo, travel
from school_finder.normalize import normalize_date, normalize_time
from school_finder.travel import (
    GoogleRoutes,
    MemoryCache,
    add_travel,
    current_school_year,
    next_school_day,
    plan_trips,
)

TZ = ZoneInfo("America/Los_Angeles")
HOME = geo.Origin(37.30, -121.90, "home")


def test_next_school_day_skips_weekend():
    assert next_school_day(datetime(2026, 11, 6, 20, 0, tzinfo=TZ)) == date(2026, 11, 9)  # Fri->Mon
    assert next_school_day(datetime(2026, 11, 2, 9, 0, tzinfo=TZ)) == date(2026, 11, 3)   # Mon->Tue


def test_current_school_year():
    assert current_school_year(date(2026, 11, 1)) == "2026-27"
    assert current_school_year(date(2027, 3, 1)) == "2026-27"
    assert current_school_year(date(2027, 8, 1)) == "2027-28"


def test_plan_uses_published_times_and_defaults():
    rows = [{"ppin": "A", "start_time": "07:50", "end_time": "15:10"}, {"ppin": "B"}]
    a, b = plan_trips(rows, date(2026, 11, 3), TZ, 30, time(8), time(15))
    assert a.am_depart.strftime("%H:%M") == "07:20" and a.pm_depart.strftime("%H:%M") == "15:10"
    assert not a.start_assumed
    assert b.am_depart.strftime("%H:%M") == "07:30" and b.start_assumed and b.end_assumed


class StubProvider:
    name = "stub"

    def __init__(self):
        self.calls = []

    def matrix(self, origins, destinations, depart_utc):
        self.calls.append((len(origins), len(destinations), depart_utc))
        n = max(len(origins), len(destinations))
        # 10 min + 1 min per index, 5 miles each
        return {((i, 0) if len(origins) > 1 else (0, i)): (600 + 60 * i, 8046.72) for i in range(n)}


def rows():
    return [{"ppin": "A", "lat": 37.35, "lon": -121.89, "start_time": "08:00", "end_time": "15:00"},
            {"ppin": "B", "lat": 37.29, "lon": -121.95},
            {"ppin": "C", "lat": None, "lon": None}]


def test_add_travel_routes_and_caches():
    now = datetime(2026, 11, 2, 21, 0, tzinfo=TZ)
    prov, cache = StubProvider(), MemoryCache()
    rs = rows()
    status = add_travel(rs, HOME, prov, cache, now=now)
    assert status["day"] == "2026-11-03" and status["routed"] == 2
    a, b, c = rs
    assert a["miles"] == pytest.approx(3.5, abs=0.2) and c["miles"] is None
    assert a["am_minutes"] == 10 and a["drive_miles"] == 5.0 and a["pm_minutes"] == 10
    assert b["am_depart"] == "07:30" and b["start_assumed"]
    assert "am_minutes" not in c
    # AM: one call (both leave 07:30); PM: one call (both leave school 15:00); UTC conversion
    assert len(prov.calls) == 2
    assert prov.calls[0][2] == datetime(2026, 11, 3, 15, 30, tzinfo=ZoneInfo("UTC"))
    # second run is served from cache
    rs2 = rows()
    add_travel(rs2, HOME, prov, cache, now=now)
    assert len(prov.calls) == 2 and rs2[0]["am_minutes"] == 10


def test_add_travel_without_provider_gives_straight_line_only():
    rs = rows()
    status = add_travel(rs, HOME, None, MemoryCache(), now=datetime(2026, 11, 2, tzinfo=TZ))
    assert rs[0]["miles"] is not None and "am_minutes" not in rs[0]
    assert status["provider"] is None


def test_cost_cap():
    rs = rows()
    status = add_travel(rs, HOME, StubProvider(), MemoryCache(),
                        now=datetime(2026, 11, 2, tzinfo=TZ), max_schools=1)
    assert status["routed"] == 1 and "am_minutes" not in rs[1]


class FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, data):
        self.data, self.sent = data, None

    def post(self, url, json=None, headers=None):
        self.sent = (url, json, headers)
        return FakeResp(self.data)

    def get(self, url, params=None):
        self.sent = (url, params)
        return FakeResp(self.data)


def test_google_routes_request_and_parse():
    client = FakeClient([
        {"originIndex": 0, "destinationIndex": 0, "status": {}, "condition": "ROUTE_EXISTS",
         "distanceMeters": 16093, "duration": "1500s"},
        {"originIndex": 0, "destinationIndex": 1, "status": {"code": 5},
         "condition": "ROUTE_NOT_FOUND"},
    ])
    out = GoogleRoutes("k", client).matrix([(1.0, 2.0)], [(3.0, 4.0), (5.0, 6.0)],
                                           datetime(2026, 11, 3, 15, 30, tzinfo=ZoneInfo("UTC")))
    assert out == {(0, 0): (1500.0, 16093.0)}
    url, body, headers = client.sent
    assert url == travel.ROUTES_URL
    assert body["routingPreference"] == "TRAFFIC_AWARE_OPTIMAL" and body["travelMode"] == "DRIVE"
    assert body["departureTime"] == "2026-11-03T15:30:00Z"
    assert body["origins"][0]["waypoint"]["location"]["latLng"] == {"latitude": 1.0, "longitude": 2.0}
    assert "status" in headers["X-Goog-FieldMask"] and headers["X-Goog-Api-Key"] == "k"


def test_geocode_and_origin_parsing():
    client = FakeClient({"result": {"addressMatches": [
        {"matchedAddress": "1 MAIN ST, SAN JOSE, CA, 95112", "coordinates": {"x": -121.9, "y": 37.3}}]}})
    o = geo.geocode("1 Main St, San Jose, CA", client)
    assert (o.lat, o.lon) == (37.3, -121.9) and o.label == "1 Main St, San Jose, Ca, 95112"
    with pytest.raises(geo.OriginError):
        geo.geocode("nowhere", FakeClient({"result": {"addressMatches": []}}))
    assert geo.resolve_origin("37.33, -121.88") == geo.Origin(37.33, -121.88, "37.33, -121.88")
    assert geo.parse_latlon("not coords") is None
    assert geo.haversine_miles(37.3382, -121.8863, 37.4419, -122.1430) == pytest.approx(15.6, abs=0.3)


def test_current_location_fallbacks(monkeypatch):
    import dataclasses

    monkeypatch.setattr(geo, "_corelocation", lambda: (37.1, -121.1))
    assert geo.resolve_origin("my current location") == geo.Origin(37.1, -121.1, "current location")

    monkeypatch.setattr(geo, "_corelocation", lambda: None)
    monkeypatch.setattr(geo, "settings", dataclasses.replace(geo.settings, home_address=None))
    monkeypatch.setattr(geo, "_ip_location", lambda: (37.2, -121.2, "San Jose, California"))
    o = geo.resolve_origin("here")
    assert not o.precise and "IP-based" in o.label

    monkeypatch.setattr(geo, "_ip_location", lambda: None)
    with pytest.raises(geo.OriginError):
        geo.resolve_origin("current location")
    with pytest.raises(geo.OriginError):
        geo.resolve_origin("home")  # no HOME_ADDRESS


def test_normalize_time_and_date():
    assert normalize_time("8:05 AM") == "08:05"
    assert normalize_time("3:10 p.m.") == "15:10"
    assert normalize_time("12:00 pm") == "12:00"
    assert normalize_time("15:20") == "15:20"
    assert normalize_time("around eight") is None
    assert normalize_date("2026-08-19") == "2026-08-19"
    assert normalize_date("Aug 19") is None
