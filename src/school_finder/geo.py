"""Starting locations: a typed address, a saved home address, or the Mac's current location."""

from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
from dataclasses import dataclass

from .config import settings

log = logging.getLogger(__name__)

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
CURRENT_WORDS = {"current location", "my current location", "my location", "here",
                 "where i am", "current"}
HOME_WORDS = {"home", "my home", "my house", "my address"}


class OriginError(ValueError):
    pass


@dataclass(frozen=True)
class Origin:
    lat: float
    lon: float
    label: str
    precise: bool = True      # False for IP-based (city-level) locations

    @property
    def key(self) -> str:
        """Cache key: ~100 m grid, so tiny GPS jitter reuses cached drive times."""
        return f"{self.lat:.3f},{self.lon:.3f}"


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_latlon(text: str) -> tuple[float, float] | None:
    m = re.fullmatch(r"\s*(-?\d{1,2}\.\d+)\s*[, ]\s*(-?\d{1,3}\.\d+)\s*", text)
    return (float(m.group(1)), float(m.group(2))) if m else None


def geocode(address: str, client=None) -> Origin:
    """US address -> coordinates with the free US Census geocoder (no API key)."""
    if client is None:
        import httpx

        client = httpx.Client(timeout=15)
    resp = client.get(CENSUS_URL, params={"address": address, "benchmark": "Public_AR_Current",
                                          "format": "json"})
    resp.raise_for_status()
    matches = resp.json().get("result", {}).get("addressMatches", [])
    if not matches:
        raise OriginError(f"Couldn't find the address '{address}'. Include street, city and state.")
    c = matches[0]["coordinates"]
    return Origin(lat=float(c["y"]), lon=float(c["x"]), label=matches[0]["matchedAddress"].title())


def _corelocation() -> tuple[float, float] | None:
    """macOS location via CoreLocationCLI (brew install corelocationcli), if installed."""
    exe = shutil.which("CoreLocationCLI") or shutil.which("corelocationcli")
    if not exe:
        return None
    for args in (["--format", "%latitude %longitude"], ["-once", "-format", "%latitude %longitude"]):
        try:
            out = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20).stdout
        except (subprocess.SubprocessError, OSError):
            continue
        ll = parse_latlon(out.strip().splitlines()[-1]) if out.strip() else None
        if ll:
            return ll
    return None


def _ip_location(client=None) -> tuple[float, float, str] | None:
    import httpx

    try:
        client = client or httpx.Client(timeout=10)
        data = client.get("https://ipinfo.io/json").json()
        lat, lon = (float(x) for x in data["loc"].split(","))
        return lat, lon, f"{data.get('city', '?')}, {data.get('region', '')}".strip(", ")
    except Exception:  # network, bad JSON, missing loc
        return None


def current_location() -> Origin:
    ll = _corelocation()
    if ll:
        return Origin(ll[0], ll[1], "current location")
    if settings.home_address:
        log.warning("Current location unavailable (install CoreLocationCLI); using HOME_ADDRESS")
        return resolve_origin(settings.home_address)
    ip = _ip_location()
    if ip:
        log.warning("Using approximate city-level location from your IP (%s). For accuracy, "
                    "`brew install corelocationcli` or set HOME_ADDRESS in .env.", ip[2])
        return Origin(ip[0], ip[1], f"approx. {ip[2]} (IP-based)", precise=False)
    raise OriginError("Couldn't get your current location. Give an address, set HOME_ADDRESS "
                      "in .env, or `brew install corelocationcli`.")


def resolve_origin(text: str) -> Origin:
    t = text.strip()
    key = t.lower().strip(" .")
    if key in CURRENT_WORDS:
        return current_location()
    if key in HOME_WORDS:
        if not settings.home_address:
            raise OriginError("Set HOME_ADDRESS in .env to use 'home'.")
        o = geocode(settings.home_address)
        return Origin(o.lat, o.lon, "home")
    ll = parse_latlon(t)
    if ll:
        return Origin(ll[0], ll[1], t)
    return geocode(t)
