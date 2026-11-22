"""
RESQ 4.0 Geocoding Service
Calls OpenStreetMap Nominatim to resolve location strings to coordinates.
Falls back to None if confidence is low, so the UI shows text-only (no fake pin).
"""
import httpx
import os
from typing import Optional, Dict, Any

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CONFIDENCE_THRESHOLD = float(os.getenv("GEOCODE_CONFIDENCE_THRESHOLD", "0.4"))

async def geocode_location(address: str) -> Optional[Dict[str, Any]]:
    """
    Returns dict with lat, lon, confidence, source — or None if unresolvable.
    """
    if not address or address.strip() in ["Unknown location", "Pending incident location", "Missing incident location"]:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                NOMINATIM_URL,
                params={"q": address, "format": "json", "limit": 1, "countrycodes": "in"},
                headers={"User-Agent": "RESQ-4.0-Emergency-Platform/1.0"}
            )
            results = r.json()
            if results:
                importance = float(results[0].get("importance", 0))
                if importance >= CONFIDENCE_THRESHOLD:
                    return {
                        "lat": float(results[0]["lat"]),
                        "lon": float(results[0]["lon"]),
                        "confidence": importance,
                        "source": "nominatim",
                        "display_name": results[0].get("display_name", address)
                    }
    except Exception as e:
        print(f"[GeocodingService] Nominatim lookup failed for '{address}': {e}")
    return None
