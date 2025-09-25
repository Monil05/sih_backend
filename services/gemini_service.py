# ...existing code...
import os
import re
from typing import Dict, Any, Optional, List

# Gemini SDK (optional)
try:
    import google.generativeai as genai
except Exception:
    genai = None

# lightweight image handling (optional)
try:
    from PIL import Image
    from io import BytesIO
except Exception:
    Image = None
    BytesIO = None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if genai is not None and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception:
        pass

SEASON_WINDOWS = {
    "Kharif": {"sowing": "June–July", "harvest": "September–November"},
    "Rabi": {"sowing": "October–December", "harvest": "February–April"},
    "Zaid": {"sowing": "April–May", "harvest": "July–August"},
}

# --- small helpers ---
def clean_text(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
    s = re.sub(r"\*(.*?)\*", r"\1", s)
    s = s.replace('\\"', '"').replace("\\'", "'")
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def display_soil_label(name: Optional[str]) -> str:
    if not name:
        return ""
    s = str(name).strip()
    if "soil" in s.lower():
        return s
    return f"{s} soil"

def _short_soil_note(soil_type: str) -> Optional[str]:
    if not soil_type:
        return None
    s = soil_type.lower()
    if "alluvial" in s:
        return "Alluvial soils are generally fertile and hold water well."
    if "black" in s or "regur" in s:
        return "Black soils hold water well because of high clay content."
    if "sandy" in s:
        return "Sandy soils drain fast — add organic matter."
    if "clay" in s:
        return "Clay soils can be heavy; organic matter helps."
    return None

def _fmt_sow_harv_from_season_or_token(season_token: Optional[str], season_months: Optional[str], fallback_month: Optional[str]) -> (str, str): # type: ignore
    if season_token:
        s = SEASON_WINDOWS.get(season_token, {})
        return s.get("sowing", ""), s.get("harvest", "")
    if season_months and isinstance(season_months, str):
        m = re.search(r"sowing[:\s]*([A-Za-z0-9–\-,\s]+)", season_months, flags=re.IGNORECASE)
        sow = m.group(1).strip() if m else ""
        m2 = re.search(r"harvest(?:ing)?[:\s]*([A-Za-z0-9–\-,\s]+)", season_months, flags=re.IGNORECASE)
        harv = m2.group(1).strip() if m2 else ""
        return sow, harv
    return fallback_month or "", ""

def _choose_fertilizers_for_soil_and_crop(soil_type: str, ph_val: Optional[float], oc_val: Optional[float], crop_name: Optional[str]) -> List[str]:
    try:
        if ph_val is not None:
            phv = float(ph_val)
            if phv < 6.0:
                return ["Compost", "Lime"]
            elif phv > 7.5:
                return ["Compost", "Micronutrient mix"]
            else:
                return ["Compost", "N-P-K mix"]
    except Exception:
        pass
    s = (soil_type or "").lower()
    if "black" in s:
        return ["Compost", "N-P-K mix"]
    if "alluvial" in s or "loamy" in s:
        return ["Compost", "N-P-K mix"]
    if "sandy" in s:
        return ["Compost", "N-P-K mix"]
    return ["Compost", "N-P-K mix"]

# --- new: extract explicit month referenced in free text query ---
_MONTHS_MAP = {
    "jan": "January", "january": "January",
    "feb": "February", "february": "February",
    "mar": "March", "march": "March",
    "apr": "April", "april": "April",
    "may": "May",
    "jun": "June", "june": "June",
    "jul": "July", "july": "July",
    "aug": "August", "august": "August",
    "sep": "September", "sept": "September", "september": "September",
    "oct": "October", "october": "October",
    "nov": "November", "november": "November",
    "dec": "December", "december": "December",
}

_month_pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in _MONTHS_MAP.keys()) + r")\b", flags=re.IGNORECASE)

def extract_month_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _month_pattern.search(text)
    if not m:
        return None
    key = m.group(1).lower()
    return _MONTHS_MAP.get(key)

def month_to_season(month_name: Optional[str]) -> Optional[str]:
    if not month_name:
        return None
    mn = month_name.strip().lower()
    if mn in ("june", "july", "august", "september", "october"):
        return "Kharif"
    if mn in ("november", "december", "january", "february", "march"):
        return "Rabi"
    if mn in ("april", "may"):
        return "Zaid"
    return None

# --- NEW: detect "what month do i grow X in" (improved & robust)
# We'll check multiple phrasings and extract crop name.
_CROP_PATTERNS = [
    r"\bwhat\s+month\s+do\s+i\s+grow\s+([a-zA-Z0-9\s\-\&]+?)(?:\s+in\b|\s*\?|$)",
    r"\bwhen\s+do\s+i\s+grow\s+([a-zA-Z0-9\s\-\&]+?)(?:\s+in\b|\s*\?|$)",
    r"\bwhen\s+should\s+i\s+plant\s+([a-zA-Z0-9\s\-\&]+?)(?:\s+in\b|\s*\?|$)",
    r"\bwhen\s+should\s+i\s+grow\s+([a-zA-Z0-9\s\-\&]+?)(?:\s+in\b|\s*\?|$)",
    r"\bwhen\s+to\s+plant\s+([a-zA-Z0-9\s\-\&]+?)(?:\s+in\b|\s*\?|$)",
    r"\bwhen\s+to\s+grow\s+([a-zA-Z0-9\s\-\&]+?)(?:\s+in\b|\s*\?|$)",
    r"\bwhat\s+month\s+is\s+best\s+to\s+grow\s+([a-zA-Z0-9\s\-\&]+?)(?:\s+in\b|\s*\?|$)",
]

def extract_crop_from_query(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    t = text.strip()
    for p in _CROP_PATTERNS:
        m = re.search(p, t, flags=re.IGNORECASE)
        if m:
            crop_raw = m.group(1).strip()
            # remove trailing words like 'this' or 'next' or 'now' or 'in punjab' etc.
            crop_clean = re.sub(r"\b(in|this|next|now|here|there)\b.*$", "", crop_raw, flags=re.IGNORECASE).strip()
            # remove punctuation
            crop_clean = re.sub(r"[^\w\s\-\&]", "", crop_clean).strip()
            if crop_clean:
                # Title-case for display
                return crop_clean.title()
    return None

# Small built-in crop-month hints (safe default)
_CROP_MONTH_HINTS = {
    "rice": ("June–July", "September–November"),
    "paddy": ("June–July", "September–November"),
    "wheat": ("October–December", "February–April"),
    "maize": ("June–July", "September–October"),
    "corn": ("June–July", "September–October"),
    "cotton": ("June–July", "October–November"),
    "soybean": ("June–July", "September–October"),
    "sorghum": ("June–July", "September–October"),
    "jowar": ("June–July", "September–October"),
    "bajra": ("May–June", "September"),
    "mustard": ("October–November", "February"),
    "groundnut": ("June–July", "September–October"),
}

# --- image classifier helper (simple, local heuristic) ---
def classify_soil_image(image_bytes: Optional[bytes]) -> Optional[str]:
    """
    Lightweight local image heuristic to suggest a soil type.
    Returns one of: "Sandy", "Clay", "Loamy" or None on failure.
    - Requires Pillow (PIL). If PIL not available, returns None.
    - This is a heuristic fallback; replace with real ML model when available.
    """
    if not image_bytes:
        return None
    if Image is None or BytesIO is None:
        return None
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        img = img.resize((64, 64))
        pixels = list(img.getdata())
        if not pixels:
            return None
        # compute average RGB and simple color stats
        r_avg = sum(p[0] for p in pixels) / len(pixels)
        g_avg = sum(p[1] for p in pixels) / len(pixels)
        b_avg = sum(p[2] for p in pixels) / len(pixels)
        brightness = (r_avg + g_avg + b_avg) / 3.0
        rg_ratio = (r_avg + 1.0) / (g_avg + 1.0)

        # Heuristic rules (tweak as needed)
        # Bright, pale -> sandy
        if brightness > 170 and rg_ratio < 1.1:
            return "Sandy"
        # Relatively reddish/darker -> clay
        if r_avg > g_avg * 1.1 and brightness < 160:
            return "Clay"
        # Greenish / balanced -> loamy (organic content)
        if g_avg >= r_avg and g_avg >= b_avg:
            return "Loamy"
        # fallback based on brightness
        if brightness < 120:
            return "Clay"
        return "Loamy"
    except Exception:
        return None

# --- build but-block (unchanged from your file) ---
def _build_but_block(farmer_reported_soil: str,
                     soil_specific_entries: List[Dict[str, Any]],
                     ph_val: Optional[float],
                     oc_val: Optional[float],
                     temperature: Optional[float],
                     month_name: Optional[str],
                     season: Optional[str],
                     season_months: Optional[str]) -> str:
    soil_label = display_soil_label(farmer_reported_soil) if farmer_reported_soil else "the reported soil"
    if soil_specific_entries:
        segments = []
        for entry in soil_specific_entries:
            crop_name = entry.get("crop") or entry.get("name") or ""
            entry_season = entry.get("season")
            sow, harv = _fmt_sow_harv_from_season_or_token(entry_season, season_months, month_name)
            ferts = _choose_fertilizers_for_soil_and_crop(farmer_reported_soil, ph_val, oc_val, crop_name)
            parts = []
            if sow:
                parts.append(f"Sowing: {sow}")
            if harv:
                parts.append(f"Harvest: {harv}")
            if ferts:
                parts.append(f"Fertilizer: {', '.join(ferts[:2])}")
            if parts:
                segments.append(f"{crop_name} — " + ". ".join(parts) + ".")
            else:
                segments.append(f"{crop_name}.")
        return f"But if you truly have {soil_label}: " + " ".join(segments)
    ferts = _choose_fertilizers_for_soil_and_crop(farmer_reported_soil, ph_val, oc_val, None)
    return f"But if you truly have {soil_label}: consider crops suited to that soil. Fertilizer: {', '.join(ferts[:2])}."

def _ensure_but_block_present(out_text: str,
                              confirmed: bool,
                              farmer_reported_soil: Optional[str],
                              ph_val: Optional[float],
                              oc_val: Optional[float],
                              temperature: Optional[float],
                              month_name: Optional[str],
                              season: Optional[str],
                              season_months: Optional[str],
                              excel_service = None) -> str:
    if confirmed or not farmer_reported_soil:
        return out_text
    out_lower = (out_text or "").lower()
    has_but = False
    try:
        if re.search(r'\bbut\s+if\b', out_lower) and farmer_reported_soil.lower() in out_lower:
            has_but = True
    except Exception:
        has_but = False
    if has_but:
        m = re.search(r'\bbut\b(.*)$', out_text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            but_part = m.group(1).lower()
            if any(k in but_part for k in ("sowing", "harvest", "fertil", "fertilizer", "fertilizers")):
                return out_text
    entries = []
    try:
        if excel_service is not None:
            entries = excel_service.query_crops_for_soil_with_seasons(farmer_reported_soil, temperature, season, limit=3)
            if not entries:
                names = excel_service.query_crops_for_soil(farmer_reported_soil, temperature, season, limit=3)
                entries = [{"crop": n, "season": None} for n in names]
    except Exception:
        entries = []
    block = _build_but_block(farmer_reported_soil, entries, ph_val, oc_val, temperature, month_name, season, season_months)
    if not block:
        return out_text
    if has_but:
        return out_text.strip() + "\n\n" + block
    return out_text.strip() + "\n\n" + block

# --- deterministic fallback (unchanged) ---
def _fallback_response(
    confirmed: bool,
    soil_type: str,
    state: Optional[str],
    season: str,
    season_months: str,
    crops: Any,
    temperature: Optional[float],
    month_name: Optional[str],
    expected_soils: Optional[List[str]],
    farmer_reported_soil: Optional[str],
    ph_val: Optional[float],
    oc_val: Optional[float],
    excel_service = None
) -> str:
    parts = []
    top_candidates = []
    if isinstance(crops, dict):
        top_candidates = crops.get("crops", []) or []
    elif isinstance(crops, list):
        top_candidates = crops
    else:
        top_candidates = []
    soil_label = display_soil_label(soil_type)
    if confirmed:
        parts.append(f"Based on our data, your reported {soil_label} is correct.")
        if top_candidates:
            sow_text, harv_text = _fmt_sow_harv_from_season_or_token(None, season_months, month_name)
            if sow_text and harv_text:
                parts.append(f"For the {season} season on {soil_label}, top choices: {', '.join(top_candidates[:2])}. Sowing: {sow_text}. Harvest: {harv_text}.")
            elif sow_text:
                parts.append(f"For the {season} season on {soil_label}, top choices: {', '.join(top_candidates[:2])}. Sowing: {sow_text}.")
            else:
                parts.append(f"For the {season} season on {soil_label}, top choices: {', '.join(top_candidates[:2])}.")
        else:
            parts.append("No clear DB crop match found; choose crops suited to the season and water availability.")
        note = _short_soil_note(soil_label)
        if note:
            parts.append(note)
        ferts = _choose_fertilizers_for_soil_and_crop(soil_label, ph_val, oc_val, None)
        parts.append(f"Fertilizer: {', '.join(ferts[:2])}. Get a soil test for exact doses.")
        if temperature is not None or month_name:
            t = f"Current temperature: {round(float(temperature),1)}°C." if temperature is not None else ""
            m = f"Month: {month_name}." if month_name else ""
            parts.append((t + " " + m).strip())
        return clean_text("\n\n".join([p for p in parts if p]))
    if expected_soils:
        parts.append(f"According to our data, {soil_label} is not common in {state}. Common soils in {state}: {', '.join(expected_soils)}.")
    else:
        parts.append(f"According to our data, we could not find an exact match for {soil_label} in {state}.")
    region_crops = []
    if expected_soils and excel_service:
        for s in expected_soils:
            info = excel_service.query_crops(state, s, temperature, season)
            if isinstance(info, dict):
                for c in info.get("crops", []):
                    if c not in region_crops:
                        region_crops.append(c)
            if len(region_crops) >= 3:
                break
    if region_crops:
        sow_text, harv_text = _fmt_sow_harv_from_season_or_token(None, season_months, month_name)
        if sow_text and harv_text:
            parts.append(f"For these soils, top choices: {', '.join(region_crops[:3])}. Sowing: {sow_text}. Harvest: {harv_text}.")
        elif sow_text:
            parts.append(f"For these soils, top choices: {', '.join(region_crops[:3])}. Sowing: {sow_text}.")
        else:
            parts.append(f"For these soils, top choices: {', '.join(region_crops[:3])}.")
    else:
        if top_candidates:
            parts.append(f"Top choices: {', '.join(top_candidates[:2])}.")
        else:
            if season and season.lower() == "kharif":
                parts.append(f"Top choices: Rice (Paddy), Maize. Sowing: June–July. Harvest: Sept–Nov.")
            else:
                parts.append(f"Top choices: choose crops suited to {season} and local water availability.")
    note = _short_soil_note(soil_label)
    if note:
        parts.append(note)
    if (ph_val is None) and (oc_val is None):
        parts.append("Fertilizer: Compost, Cow dung manure. Get a soil test for exact doses.")
    else:
        parts.append("Fertilizer: N-P-K (balanced), Compost. Get a soil test for exact doses.")
    if temperature is not None or month_name:
        t = f"Current temperature: {round(float(temperature),1)}°C." if temperature is not None else ""
        m = f"Month: {month_name}." if month_name else ""
        parts.append((t + " " + m).strip())
    return clean_text("\n\n".join([p for p in parts if p]))

# --- main exported function (unchanged) ---
def generate_advice(
    soil_info: Dict[str, Any],
    weather: Dict[str, Any],
    season: str,
    season_months: str,
    crops: Any,
    query: Optional[str] = None,
    state: Optional[str] = None,
    verification_context: Optional[str] = None,
    farmer_reported_soil: Optional[str] = None,
    confirmed: Optional[bool] = None,
    month_name: Optional[str] = None,
    excel_service = None
) -> str:
    """
    Generate short advice. Minimal change: if `query` contains an explicit month,
    use that month (and infer season) instead of the supplied month_name.
    Also: if query asks 'what month do I grow <crop> in' prefer full advice format (not the short line).
    All other behavior preserved.
    """

    # ---------- NEW: handle crop-month question by injecting crop into 'crops' (minimal change) ----------
    crop_from_query = extract_crop_from_query(query)
    if crop_from_query:
        # ensure the candidate-crops include this crop so the normal flow (Gemini/fallback) uses it
        try:
            if isinstance(crops, dict):
                existing = list(crops.get("crops", []) or [])
                # prefer canonical title-case of crop
                if crop_from_query not in existing:
                    existing.insert(0, crop_from_query)
                crops = {"crops": existing}
            elif isinstance(crops, list):
                if crop_from_query not in crops:
                    crops = [crop_from_query] + crops
                else:
                    # move to front
                    crops = [crop_from_query] + [c for c in crops if c != crop_from_query]
            else:
                crops = {"crops": [crop_from_query]}
        except Exception:
            crops = {"crops": [crop_from_query]}
    # ---------- end crop-month handling (no early return) ----------

    # If query explicitly mentions a month, override month_name and season
    month_override = extract_month_from_text(query) if query else None
    if month_override:
        month_name = month_override
        inferred_season = month_to_season(month_override)
        if inferred_season:
            season = inferred_season
            season_months = SEASON_WINDOWS.get(season, {}).get("sowing", "") + " / " + SEASON_WINDOWS.get(season, {}).get("harvest", "")

    # ensure defaults
    soil_type = soil_info.get("soil_type") if isinstance(soil_info, dict) else (farmer_reported_soil or "Unknown")
    if confirmed is None:
        confirmed = bool(isinstance(soil_info, dict) and soil_info.get("verified", False))
    temp_val = None
    try:
        temp_val = weather.get("temperature") if isinstance(weather, dict) else None
    except Exception:
        temp_val = None
    expected_soils = None
    if isinstance(soil_info, dict):
        expected_soils = soil_info.get("expected_soils") or None

    # Build short structured prompt for Gemini (keeps earlier style instruction)
    style_instruction = (
        "You are an agricultural assistant. Short, farmer-friendly, 3-5 short paragraphs. "
        "Flow: (A) If match confirmed: one affirmation sentence mentioning the soil. (B) 1-2 crop choices + sowing/harvest months. "
        "(C) One short soil fact. (D) 1-2 fertilizer names (no units) + 'Get a soil test for exact doses.' "
        "If not confirmed: start with 'According to our data...' listing common soils for the state, then same flow. "
        "Always include current temperature and month. Avoid markdown and escaped quotes."
    )
    structured_input = {
        "state": state,
        "soil_type": soil_type,
        "confirmed": confirmed,
        "season": season,
        "season_months": season_months,
        "month": month_name,
        "temperature": temp_val,
        "candidate_crops": crops.get("crops") if isinstance(crops, dict) else crops,
        "expected_soils": expected_soils,
        "verification_context": verification_context,
        "farmer_reported_soil": farmer_reported_soil,
        "query": query
    }
    prompt = f"{style_instruction}\n\nInput:\n{structured_input}\n\nProduce the short advice exactly in the flow."

    # Try Gemini first (if configured)
    if genai is not None and GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel("gemini-2.5-pro")
            resp = model.generate_content(prompt)
            text = None
            if hasattr(resp, "text"):
                text = resp.text
            elif isinstance(resp, dict):
                text = resp.get("output") or resp.get("text")
            if text:
                out = clean_text(text)
                # ensure fertilizer mention
                low = out.lower()
                if not any(k in low for k in ("fertil", "compost", "n-p-k", "cow dung", "dap", "urea")):
                    out = out.strip() + "\n\nFertilizer: Compost. Get a soil test for exact doses."
                ph_val = soil_info.get("details", {}).get("ph") if isinstance(soil_info, dict) else None
                oc_val = soil_info.get("details", {}).get("organic_carbon") if isinstance(soil_info, dict) else None
                out2 = _ensure_but_block_present(
                    out_text=out,
                    confirmed=confirmed,
                    farmer_reported_soil=farmer_reported_soil,
                    ph_val=ph_val,
                    oc_val=oc_val,
                    temperature=temp_val,
                    month_name=month_name,
                    season=season,
                    season_months=season_months,
                    excel_service=excel_service
                )
                return out2
        except Exception:
            pass

    # Fallback deterministic short response
    ph_val = soil_info.get("details", {}).get("ph") if isinstance(soil_info, dict) else None
    oc_val = soil_info.get("details", {}).get("organic_carbon") if isinstance(soil_info, dict) else None
    base = _fallback_response(
        confirmed=confirmed,
        soil_type=soil_type,
        state=state,
        season=season,
        season_months=season_months,
        crops=crops,
        temperature=temp_val,
        month_name=month_name,
        expected_soils=expected_soils,
        farmer_reported_soil=farmer_reported_soil,
        ph_val=ph_val,
        oc_val=oc_val,
        excel_service=excel_service
    )
    return _ensure_but_block_present(
        out_text=base,
        confirmed=confirmed,
        farmer_reported_soil=farmer_reported_soil,
        ph_val=ph_val,
        oc_val=oc_val,
        temperature=temp_val,
        month_name=month_name,
        season=season,
        season_months=season_months,
        excel_service=excel_service
    )
