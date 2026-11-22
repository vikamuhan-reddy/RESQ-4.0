"""
RESQ 4.0 location candidates.
Looks up a place name on OpenStreetMap (Nominatim), limited to the city, and returns candidates.
Nothing is pinned automatically: an operator must pick one (or click the map) to confirm.
"""
import os
from typing import List, Dict, Any

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# lon_min,lat_max,lon_max,lat_min - Chennai metro by default
CITY_VIEWBOX = os.getenv("GEOCODE_VIEWBOX", "80.05,13.30,80.35,12.80")


async def find_candidates(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    if not query or not query.strip():
        return []
    async with httpx.AsyncClient(timeout=6.0) as client:
        r = await client.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": limit, "viewbox": CITY_VIEWBOX, "bounded": 1},
            headers={"User-Agent": "RESQ-4.0-hackathon-demo/1.0"},  # Nominatim policy: identify the app
        )
        r.raise_for_status()
    return [{"lat": float(x["lat"]), "lon": float(x["lon"]), "name": x.get("display_name", query)} for x in r.json()]
