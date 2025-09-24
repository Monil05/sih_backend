# services/weather_service.py
import os
import requests
from typing import Optional, Dict

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
SOILGRIDS_BASE = "https://rest.isric.org/soilgrids/v2.0/properties/query"

def _avg_values(arr):
    """
    Given an array of dicts like [{'value': 6.5}, ...] return average or None.
    """
    if not arr or not isinstance(arr, list):
        return None
    vals = [v.get("value") for v in arr if isinstance(v, dict) and v.get("value") is not None]
    if not vals:
        return None
    try:
        return sum(vals) / len(vals)
    except Exception:
        return None

def get_temperature_by_pincode(pincode: str) -> Optional[float]:
    """
    Returns temperature in Celsius (float) or None.
    Uses OpenWeather current weather endpoint with zip code.
    """
    try:
        if not OPENWEATHER_API_KEY or not pincode:
            return None
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"zip": f"{pincode},IN", "appid": OPENWEATHER_API_KEY, "units": "metric"},
            timeout=8,
        )
        r.raise_for_status()
        j = r.json()
        main = j.get("main") if isinstance(j, dict) else None
        if main and ("temp" in main):
            try:
                return float(main.get("temp"))
            except Exception:
                return None
        return None
    except Exception:
        return None

def _geocode_with_openweather(pincode: str) -> Optional[Dict[str, float]]:
    """
    Use OpenWeather geocoding for zip -> lat/lon
    Returns {'lat': float, 'lon': float} or None.
    """
    if not OPENWEATHER_API_KEY or not pincode:
        return None
    try:
        url = f"http://api.openweathermap.org/geo/1.0/zip"
        r = requests.get(url, params={"zip": f"{pincode},IN", "appid": OPENWEATHER_API_KEY}, timeout=8)
        r.raise_for_status()
        data = r.json()
        lat = data.get("lat") or data.get("latitude")
        lon = data.get("lon") or data.get("longitude")
        if lat is None or lon is None:
            coord = data.get("coord", {})
            lat = coord.get("lat")
            lon = coord.get("lon")
        if lat is None or lon is None:
            return None
        return {"lat": float(lat), "lon": float(lon)}
    except Exception:
        return None

def _query_soilgrids(lat: float, lon: float, properties: str = "ph") -> Optional[Dict]:
    """
    Query SoilGrids REST API for given properties (comma-separated string).
    Returns parsed JSON or None.
    """
    try:
        params = {"lat": lat, "lon": lon, "property": properties}
        r = requests.get(SOILGRIDS_BASE, params=params, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def get_weather_by_pincode(pincode: str) -> Dict[str, Optional[float]]:
    """
    Returns a dict with:
      {"temperature": float|None, "ph": float|None, "moisture": float|None}

    - temperature: from OpenWeather (current temp in Celsius)
    - ph: average pH from SoilGrids (if lat/lon available)
    - moisture: attempt to read 'moisture' from SoilGrids if present, otherwise None

    This function is defensive: if any upstream call fails, values will be None.
    """
    result = {"temperature": None, "ph": None, "moisture": None}
    try:
        # temperature
        temp = get_temperature_by_pincode(pincode)
        result["temperature"] = temp

        # geocode -> soilgrids for pH & (optional) moisture
        latlon = _geocode_with_openweather(pincode) if pincode else None
        if latlon:
            sg = _query_soilgrids(latlon["lat"], latlon["lon"], properties="ph,moisture")
            if sg and isinstance(sg, dict):
                props = sg.get("properties", {}) or {}
                ph_vals = {}
                moisture_vals = {}
                # handle different possible shapes safely
                try:
                    ph_vals = props.get("ph", {}).get("values", []) if isinstance(props.get("ph"), dict) else []
                except Exception:
                    ph_vals = []
                try:
                    moisture_vals = props.get("moisture", {}).get("values", []) if isinstance(props.get("moisture"), dict) else []
                except Exception:
                    moisture_vals = []

                ph_avg = _avg_values(ph_vals)
                moisture_avg = _avg_values(moisture_vals)
                result["ph"] = ph_avg
                result["moisture"] = moisture_avg

        return result
    except Exception:
        # Always return the dict shape even on unexpected failure
        return result
