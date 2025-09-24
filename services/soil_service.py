# services/soil_service.py
import os
import requests
from typing import Optional, Dict, Any

from services import excel_service  # uses the excel_service above

BHUWAN_GEOCODING_TOKEN = os.getenv("BHUWAN_GEOCODING_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
SOILGRIDS_BASE = "https://rest.isric.org/soilgrids/v2.0/properties/query"

def _geocode_with_bhuvan(pincode: str) -> Optional[Dict[str, float]]:
    if not BHUWAN_GEOCODING_TOKEN or not pincode:
        return None
    try:
        url = "https://bhuvan-portal1.nrsc.gov.in/api/geocode"
        r = requests.get(url, params={"pincode": pincode, "token": BHUWAN_GEOCODING_TOKEN}, timeout=10)
        r.raise_for_status()
        j = r.json()
        # Try several possible response shapes
        if isinstance(j, dict):
            # common keys
            if "latitude" in j and "longitude" in j:
                return {"lat": float(j["latitude"]), "lon": float(j["longitude"])}
            if "lat" in j and "lon" in j:
                return {"lat": float(j["lat"]), "lon": float(j["lon"])}
            # sometimes an inner 'data' object
            if "data" in j and isinstance(j["data"], dict):
                d = j["data"]
                if "latitude" in d and "longitude" in d:
                    return {"lat": float(d["latitude"]), "lon": float(d["longitude"])}
        return None
    except Exception:
        return None

def _geocode_with_openweather(pincode: str) -> Optional[Dict[str, float]]:
    if not OPENWEATHER_API_KEY or not pincode:
        return None
    try:
        url = "http://api.openweathermap.org/geo/1.0/zip"
        r = requests.get(url, params={"zip": f"{pincode},IN", "appid": OPENWEATHER_API_KEY}, timeout=8)
        r.raise_for_status()
        j = r.json()
        lat = j.get("lat") or j.get("latitude")
        lon = j.get("lon") or j.get("longitude")
        if lat is None or lon is None:
            coord = j.get("coord", {})
            lat = coord.get("lat"); lon = coord.get("lon")
        if lat is None or lon is None:
            return None
        return {"lat": float(lat), "lon": float(lon)}
    except Exception:
        return None

def _query_soilgrids(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    try:
        params = {"lat": lat, "lon": lon, "property": "clay,sand,silt,ph,ocd"}
        r = requests.get(SOILGRIDS_BASE, params=params, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def _avg_values(arr):
    if not arr or not isinstance(arr, list):
        return None
    vals = [v.get("value") for v in arr if isinstance(v, dict) and v.get("value") is not None]
    if not vals:
        return None
    try:
        return sum(vals)/len(vals)
    except Exception:
        return None

def _classify_from_percentages(clay_avg: float, sand_avg: float, silt_avg: float) -> str:
    try:
        clay_avg = float(clay_avg or 0.0)
        sand_avg = float(sand_avg or 0.0)
        silt_avg = float(silt_avg or 0.0)
    except Exception:
        return "Loamy"
    if clay_avg >= 40:
        return "Clay"
    if sand_avg >= 70:
        return "Sandy"
    if sand_avg >= 40 and silt_avg >= 20:
        return "Sandy Loam"
    return "Loamy"

async def get_soil_type_async(
    pincode: Optional[str],
    state: Optional[str],
    city: Optional[str],
    provided_soil_type: Optional[str],
    soil_image = None
) -> Dict[str, Any]:
    """
    Returns dict with:
      {
        "soil_type": str,
        "source": str,
        "details": {...},
        "verified": bool,
        "expected_soils": [..]
      }
    Behavior:
      - If farmer provided soil and it's in Excel DB for the state -> return verified=True (early return).
      - Else, try image classifier (if image provided), then SoilGrids (lat/lon from Bhuvan then OpenWeather), then web fallback (excel_service.get_soils_for_state used by main).
    """
    try:
        unknown_tokens = ("don't know", "dont know", "unknown", "na", "n/a", "")
        provided = (provided_soil_type.strip() if provided_soil_type and str(provided_soil_type).strip() != "" else None)
        result = {"soil_type": None, "source": None, "details": {}, "verified": False, "expected_soils": []}

        # If farmer provided, first verify against Excel DB for this state (if state given)
        if provided and str(provided).strip().lower() not in unknown_tokens:
            if state:
                try:
                    exists = excel_service.check_soil_exists(state, provided)
                except Exception:
                    exists = False
                expected = excel_service.get_soils_for_state(state) or []
                result["expected_soils"] = expected
                if exists:
                    result["soil_type"] = provided
                    result["source"] = "farmer_input_verified"
                    result["verified"] = True
                    return result
                else:
                    # mark unverified but keep and attempt to infer
                    result["soil_type"] = provided
                    result["source"] = "farmer_input_unverified"
                    result["verified"] = False
                    # continue to try image/soilgrids to possibly override/infer
            else:
                # No state provided to verify; treat as unverified farmer input
                result["soil_type"] = provided
                result["source"] = "farmer_input_unverified"
                result["verified"] = False

        # 2) If an image provided, try to classify (Gemini) - may override or set a guess
        if soil_image is not None:
            try:
                contents = None
                try:
                    # UploadFile-like
                    contents = await soil_image.read()
                except Exception:
                    try:
                        contents = soil_image.file.read()
                    except Exception:
                        contents = None
                if contents:
                    from services import gemini_service
                    img_guess = None
                    try:
                        img_guess = gemini_service.classify_soil_image(contents)
                    except Exception:
                        img_guess = None
                    if img_guess:
                        # If farmer gave input and image matches it -> mark verified
                        if provided and img_guess.strip().lower() == provided.strip().lower():
                            result["soil_type"] = provided
                            result["source"] = "image+farmer_verified"
                            result["verified"] = True
                            # keep expected_soils if we have them
                            if state:
                                result["expected_soils"] = excel_service.get_soils_for_state(state) or []
                            return result
                        else:
                            # set image guess (not necessarily verified)
                            result["soil_type"] = img_guess
                            result["source"] = "image"
                            result["details"]["image_guess"] = img_guess
            except Exception:
                pass

        # 3) Use pincode -> lat/lon -> SoilGrids to infer soil and get pH/OC
        latlon = None
        if pincode:
            latlon = _geocode_with_bhuvan(pincode) or _geocode_with_openweather(pincode)
        if latlon:
            sg = _query_soilgrids(latlon["lat"], latlon["lon"])
            if sg and isinstance(sg, dict):
                props = sg.get("properties", {}) or {}
                clay_vals = props.get("clay", {}).get("values", []) if isinstance(props.get("clay"), dict) else []
                sand_vals = props.get("sand", {}).get("values", []) if isinstance(props.get("sand"), dict) else []
                silt_vals = props.get("silt", {}).get("values", []) if isinstance(props.get("silt"), dict) else []
                ph_vals = props.get("ph", {}).get("values", []) if isinstance(props.get("ph"), dict) else []
                oc_vals = props.get("ocd", {}).get("values", []) if isinstance(props.get("ocd"), dict) else []

                clay_avg = _avg_values(clay_vals)
                sand_avg = _avg_values(sand_vals)
                silt_avg = _avg_values(silt_vals)
                ph_avg = _avg_values(ph_vals)
                oc_avg = _avg_values(oc_vals)

                inferred = _classify_from_percentages(clay_avg, sand_avg, silt_avg)

                # If we had an unverified farmer-provided soil and soilgrids gives a different result,
                # keep farmer input in details and set soil_type to inferred
                if result.get("soil_type") and result.get("source") == "farmer_input_unverified":
                    if inferred and inferred.strip().lower() != str(result["soil_type"]).strip().lower():
                        result["details"]["farmer_reported"] = result["soil_type"]
                        result["soil_type"] = inferred
                        result["source"] = "soilgrids"
                        result["verified"] = False
                        result["expected_soils"] = excel_service.get_soils_for_state(state) if state else []
                    else:
                        # soilgrids agrees or no conflict -> set as inferred if none set before
                        if not result.get("soil_type"):
                            result["soil_type"] = inferred
                            result["source"] = "soilgrids"
                            result["verified"] = False
                else:
                    if not result.get("soil_type"):
                        result["soil_type"] = inferred
                        result["source"] = "soilgrids"
                        result["verified"] = False

                result["details"].update({
                    "clay_pct": clay_avg,
                    "sand_pct": sand_avg,
                    "silt_pct": silt_avg,
                    "ph": ph_avg,
                    "organic_carbon": oc_avg,
                    "latlon": latlon
                })

        # 4) As last resort if nothing found, set Unknown but include DB soils for context
        if not result.get("soil_type"):
            result["soil_type"] = "Unknown"
            result["source"] = "fallback"
            result["verified"] = False
            if state:
                result["expected_soils"] = excel_service.get_soils_for_state(state) or []

        return result
    except Exception as e:
        # safe fallback
        return {"soil_type": "Unknown", "source": "error", "details": {"error": str(e)}, "verified": False, "expected_soils": []}
