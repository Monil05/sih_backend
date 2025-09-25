import os
import requests
from typing import Optional, Dict, Any

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
BHUWAN_GEOCODING_TOKEN = os.getenv("BHUWAN_GEOCODING_TOKEN")
SOILGRIDS_BASE = "https://rest.isric.org/soilgrids/v2.0/properties/query"


def _avg_values(arr: Any) -> Optional[float]:
    if not arr or not isinstance(arr, list):
        return None
    vals = [v.get("value") for v in arr if isinstance(v, dict) and v.get("value") is not None]
    if not vals:
        return None
    try:
        return sum(vals) / len(vals)
    except Exception:
        return None

# ...existing code...
def check_openweather_key() -> Dict[str, Any]:
    """
    Validate OPENWEATHER_API_KEY quickly. Returns {'ok': bool, 'status': int, 'message': str}.
    """
    key = os.getenv("OPENWEATHER_API_KEY")
    if not key:
        return {"ok": False, "status": 0, "message": "missing OPENWEATHER_API_KEY"}
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"zip": "110001,IN", "appid": key, "units": "metric"},
            timeout=6,
        )
        if r.status_code == 200:
            return {"ok": True, "status": 200, "message": "valid"}
        if r.status_code == 401:
            return {"ok": False, "status": 401, "message": "invalid API key (401)"}
        return {"ok": False, "status": r.status_code, "message": r.text[:400]}
    except Exception as e:
        return {"ok": False, "status": -1, "message": str(e)}

def check_bhuvan() -> Dict[str, Any]:
    """
    Validate BHUWAN_GEOCODING_TOKEN quickly. Returns {'ok': bool, 'status': int, 'message': str, 'body': optional}.
    """
    token = os.getenv("BHUWAN_GEOCODING_TOKEN")
    if not token:
        return {"ok": False, "status": 0, "message": "missing BHUWAN_GEOCODING_TOKEN"}
    try:
        r = requests.get(
            "https://bhuvan-portal1.nrsc.gov.in/api/geocode",
            params={"pincode": "110001", "token": token},
            timeout=8,
        )
        if r.status_code == 200:
            try:
                j = r.json()
                # basic validation: look for lat/lon in common places
                if isinstance(j, dict) and (("latitude" in j and "longitude" in j) or ("lat" in j and "lon" in j) or ("data" in j)):
                    return {"ok": True, "status": 200, "message": "valid", "body": j}
            except Exception:
                pass
            return {"ok": False, "status": 200, "message": "response OK but unexpected body", "text": r.text[:400]}
        if r.status_code in (401, 403):
            return {"ok": False, "status": r.status_code, "message": "invalid/unauthorized token"}
        return {"ok": False, "status": r.status_code, "message": r.text[:400]}
    except Exception as e:
        return {"ok": False, "status": -1, "message": str(e)}
# ...existing code...


def _fetch_openweather_by_zip(pincode: str) -> Optional[Dict[str, Any]]:
    if not OPENWEATHER_API_KEY or not pincode:
        return None
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"zip": f"{pincode},IN", "appid": OPENWEATHER_API_KEY, "units": "metric"},
            timeout=8,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _fetch_openweather_by_latlon(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    if not OPENWEATHER_API_KEY:
        return None
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY, "units": "metric"},
            timeout=8,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _geocode_with_bhuvan(pincode: str) -> Optional[Dict[str, float]]:
    if not BHUWAN_GEOCODING_TOKEN or not pincode:
        return None
    try:
        url = "https://bhuvan-portal1.nrsc.gov.in/api/geocode"
        r = requests.get(url, params={"pincode": pincode, "token": BHUWAN_GEOCODING_TOKEN}, timeout=10)
        r.raise_for_status()
        j = r.json()
        if isinstance(j, dict):
            if "latitude" in j and "longitude" in j:
                return {"lat": float(j["latitude"]), "lon": float(j["longitude"])}
            if "lat" in j and "lon" in j:
                return {"lat": float(j["lat"]), "lon": float(j["lon"])}
            if "data" in j and isinstance(j["data"], dict):
                d = j["data"]
                if "latitude" in d and "longitude" in d:
                    return {"lat": float(d["latitude"]), "lon": float(d["longitude"])}
        return None
    except Exception:
        return None


def _query_soilgrids(lat: float, lon: float, properties: str = "ph") -> Optional[Dict]:
    try:
        params = {"lat": lat, "lon": lon, "property": properties}
        r = requests.get(SOILGRIDS_BASE, params=params, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def get_weather_by_pincode(pincode: str) -> Dict[str, Optional[float]]:
    result: Dict[str, Optional[float]] = {"temperature": None, "ph": None, "moisture": None}
    try:
        temp = None
        # try by zip first
        j = _fetch_openweather_by_zip(pincode)
        if j:
            main = j.get("main", {}) or {}
            temp = main.get("temp")
            result["temperature"] = float(temp) if temp is not None else None
        else:
            # try Bhuvan geocode -> openweather by lat/lon
            latlon = _geocode_with_bhuvan(pincode)
            if latlon:
                j2 = _fetch_openweather_by_latlon(latlon["lat"], latlon["lon"])
                if j2:
                    main = j2.get("main", {}) or {}
                    temp = main.get("temp")
                    result["temperature"] = float(temp) if temp is not None else None

        # soilgrid pH & moisture via lat/lon geocode (prefer Bhuvan, fallback OpenWeather geocode)
        latlon = _geocode_with_bhuvan(pincode) or None
        if not latlon:
            # try openweather geocode by zip endpoint
            try:
                geo = requests.get("http://api.openweathermap.org/geo/1.0/zip", params={"zip": f"{pincode},IN", "appid": OPENWEATHER_API_KEY}, timeout=8)
                geo.raise_for_status()
                gd = geo.json()
                lat = gd.get("lat") or gd.get("latitude")
                lon = gd.get("lon") or gd.get("longitude")
                if lat is not None and lon is not None:
                    latlon = {"lat": float(lat), "lon": float(lon)}
            except Exception:
                latlon = None

        if latlon:
            sg = _query_soilgrids(latlon["lat"], latlon["lon"], properties="ph,moisture")
            if sg and isinstance(sg, dict):
                props = sg.get("properties", {}) or {}
                try:
                    ph_vals = props.get("ph", {}).get("values", []) if isinstance(props.get("ph"), dict) else []
                except Exception:
                    ph_vals = []
                try:
                    moisture_vals = props.get("moisture", {}).get("values", []) if isinstance(props.get("moisture"), dict) else []
                except Exception:
                    moisture_vals = []
                result["ph"] = _avg_values(ph_vals)
                result["moisture"] = _avg_values(moisture_vals)

        return result
    except Exception:
        return result


def get_weather_and_soil_details(pincode: Optional[str]) -> Dict[str, Optional[object]]:
    result: Dict[str, Optional[object]] = {
        "temperature": None,
        "humidity": None,
        "conditions": None,
        "ph": None,
        "moisture": None,
        "source": "none",
    }
    if not pincode:
        return result

    # First try to get combined data (temperature, ph, moisture)
    basic = get_weather_by_pincode(pincode)
    result["temperature"] = basic.get("temperature")
    result["ph"] = basic.get("ph")
    result["moisture"] = basic.get("moisture")

    # Try to fetch humidity and conditions from OpenWeather; if zip fails, use Bhuvan + lat/lon
    openweather_json = _fetch_openweather_by_zip(pincode)
    if not openweather_json:
        # attempt bhuvan geocode -> openweather by latlon
        latlon = _geocode_with_bhuvan(pincode)
        if latlon:
            openweather_json = _fetch_openweather_by_latlon(latlon["lat"], latlon["lon"])

    if openweather_json:
        try:
            main = openweather_json.get("main", {}) or {}
            weather_list = openweather_json.get("weather", []) or []
            if "humidity" in main:
                try:
                    result["humidity"] = int(main.get("humidity"))
                except Exception:
                    result["humidity"] = None
            if weather_list:
                try:
                    result["conditions"] = weather_list[0].get("description")
                except Exception:
                    result["conditions"] = None
            result["source"] = "openweather"
        except Exception:
            if result.get("temperature") is not None:
                result["source"] = "partial"

    return result
