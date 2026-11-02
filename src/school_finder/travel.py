"""Traffic-aware drive times to and from schools.

Morning: leave the starting point `lead` minutes before the school's start time.
Afternoon: leave the school at its end time and drive back.
Both use predicted traffic for that time on the next school day (Mon-Fri), via the
Google Routes API route matrix. Results are cached so repeat searches are free.
Schools without a published start/end time use the defaults (08:00 / 15:00) and are
marked as assumed.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from .config import settings
from .geo import Origin, haversine_miles

log = logging.getLogger(__name__)

ROUTES_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
MAX_ELEMENTS = 100          # route matrix limit with TRAFFIC_AWARE_OPTIMAL
METERS_PER_MILE = 1609.344
LatLon = tuple[float, float]


class RouteProvider(Protocol):
    name: str

    def matrix(self, origins: Sequence[LatLon], destinations: Sequence[LatLon],
               depart_utc: datetime) -> dict[tuple[int, int], tuple[float, float]]:
        """{(origin_idx, dest_idx): (seconds, meters)} for routes that exist."""
        ...


class GoogleRoutes:
    name = "google_routes"

    def __init__(self, api_key: str, client=None):
        if client is None:
            import httpx

            client = httpx.Client(timeout=30)
        self.api_key = api_key
        self.client = client

    @staticmethod
    def _wp(p: LatLon) -> dict:
        return {"waypoint": {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}}

    def matrix(self, origins, destinations, depart_utc):
        body = {
            "origins": [self._wp(p) for p in origins],
            "destinations": [self._wp(p) for p in destinations],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
            "trafficModel": "BEST_GUESS",
            "departureTime": depart_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        resp = self.client.post(ROUTES_URL, json=body, headers={
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "originIndex,destinationIndex,status,condition,distanceMeters,duration",
        })
        resp.raise_for_status()
        out = {}
        for el in resp.json():
            if el.get("status", {}).get("code") or el.get("condition") != "ROUTE_EXISTS":
                continue
            secs = float(str(el.get("duration", "0s")).rstrip("s"))
            out[(el.get("originIndex", 0), el.get("destinationIndex", 0))] = (
                secs, float(el.get("distanceMeters", 0)))
        return out


class TravelCache(Protocol):
    def get(self, origin_key: str, ppin: str, direction: str, slot: str) -> tuple[float, float] | None: ...
    def put(self, origin_key: str, ppin: str, direction: str, slot: str, minutes: float,
            miles: float, provider: str) -> None: ...


class MemoryCache:
    def __init__(self):
        self.data: dict = {}

    def get(self, origin_key, ppin, direction, slot):
        return self.data.get((origin_key, ppin, direction, slot))

    def put(self, origin_key, ppin, direction, slot, minutes, miles, provider):
        self.data[(origin_key, ppin, direction, slot)] = (minutes, miles)


# ---------- time planning (pure) ----------

def parse_hhmm(value: str | None) -> time | None:
    if not value:
        return None
    try:
        h, m = str(value).strip()[:5].split(":")
        return time(int(h), int(m))
    except ValueError:
        return None


def next_school_day(now: datetime) -> date:
    """Next Mon-Fri strictly after today (departure times must be in the future)."""
    d = now.date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def current_school_year(today: date) -> str:
    start = today.year if today.month >= 7 else today.year - 1
    return f"{start}-{str(start + 1)[2:]}"


@dataclass
class TripPlan:
    ppin: str
    am_depart: datetime        # local, leaving the origin
    pm_depart: datetime        # local, leaving the school
    start: time
    end: time
    start_assumed: bool
    end_assumed: bool


def plan_trips(rows: Iterable[dict], day: date, tz: ZoneInfo, lead_minutes: int,
               default_start: time, default_end: time) -> list[TripPlan]:
    plans = []
    for r in rows:
        start, end = parse_hhmm(r.get("start_time")), parse_hhmm(r.get("end_time"))
        s, e = start or default_start, end or default_end
        am = datetime.combine(day, s, tz) - timedelta(minutes=lead_minutes)
        pm = datetime.combine(day, e, tz)
        plans.append(TripPlan(r["ppin"], am, pm, s, e, start is None, end is None))
    return plans


def slot(dt: datetime) -> str:
    """Cache slot: weekday + time of day, e.g. 'Tue 07:30'."""
    return dt.strftime("%a %H:%M")


# ---------- main entry ----------

def add_travel(rows: list[dict], origin: Origin, provider: RouteProvider | None,
               cache: TravelCache, now: datetime | None = None,
               day: date | None = None, max_schools: int | None = None) -> dict:
    """Add straight-line miles to every row, and AM/PM drive times to the first
    `max_schools` rows (cost guard). Returns a short status dict for display."""
    tz = ZoneInfo(settings.timezone)
    now = now or datetime.now(tz)
    day = day or next_school_day(now)
    max_schools = settings.max_route_schools if max_schools is None else max_schools

    for r in rows:
        r["miles"] = (round(haversine_miles(origin.lat, origin.lon, r["lat"], r["lon"]), 1)
                      if r.get("lat") is not None else None)
    routed = [r for r in rows if r.get("lat") is not None][:max_schools]
    status = {"origin": origin.label, "day": day.isoformat(), "routed": len(routed),
              "provider": provider.name if provider else None, "precise_origin": origin.precise}
    if not provider or not routed:
        return status

    plans = {p.ppin: p for p in plan_trips(routed, day, tz, settings.morning_lead_minutes,
                                           parse_hhmm(settings.default_start_time) or time(8),
                                           parse_hhmm(settings.default_end_time) or time(15))}
    by_ppin = {r["ppin"]: r for r in routed}
    o = (origin.lat, origin.lon)

    # group by departure time so each matrix call shares one departure time
    am_groups: dict[datetime, list[str]] = defaultdict(list)
    pm_groups: dict[datetime, list[str]] = defaultdict(list)
    for ppin, p in plans.items():
        r = by_ppin[ppin]
        r.update(start_time_used=p.start.strftime("%H:%M"), end_time_used=p.end.strftime("%H:%M"),
                 start_assumed=p.start_assumed, end_assumed=p.end_assumed,
                 am_depart=p.am_depart.strftime("%H:%M"), pm_depart=p.pm_depart.strftime("%H:%M"))
        hit = cache.get(origin.key, ppin, "am", slot(p.am_depart))
        if hit:
            r["am_minutes"], r["drive_miles"] = hit
        else:
            am_groups[p.am_depart].append(ppin)
        hit = cache.get(origin.key, ppin, "pm", slot(p.pm_depart))
        if hit:
            r["pm_minutes"] = hit[0]
        else:
            pm_groups[p.pm_depart].append(ppin)

    calls = 0
    for depart, ppins in am_groups.items():
        for i in range(0, len(ppins), MAX_ELEMENTS):
            batch = ppins[i:i + MAX_ELEMENTS]
            dests = [(by_ppin[x]["lat"], by_ppin[x]["lon"]) for x in batch]
            res = provider.matrix([o], dests, depart.astimezone(ZoneInfo("UTC")))
            calls += 1
            for (_, j), (secs, meters) in res.items():
                minutes, miles = round(secs / 60), round(meters / METERS_PER_MILE, 1)
                by_ppin[batch[j]].update(am_minutes=minutes, drive_miles=miles)
                cache.put(origin.key, batch[j], "am", slot(depart), minutes, miles, provider.name)
    for depart, ppins in pm_groups.items():
        for i in range(0, len(ppins), MAX_ELEMENTS):
            batch = ppins[i:i + MAX_ELEMENTS]
            srcs = [(by_ppin[x]["lat"], by_ppin[x]["lon"]) for x in batch]
            res = provider.matrix(srcs, [o], depart.astimezone(ZoneInfo("UTC")))
            calls += 1
            for (k, _), (secs, meters) in res.items():
                minutes = round(secs / 60)
                by_ppin[batch[k]]["pm_minutes"] = minutes
                cache.put(origin.key, batch[k], "pm", slot(depart), minutes,
                          round(meters / METERS_PER_MILE, 1), provider.name)
    status["api_calls"] = calls
    return status


def default_provider() -> RouteProvider | None:
    return GoogleRoutes(settings.google_maps_api_key) if settings.google_maps_api_key else None
