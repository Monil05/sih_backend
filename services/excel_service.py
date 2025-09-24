# services/excel_service.py
import os
import glob
import re
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
DATA_DIR = os.path.join(BASE_DIR, "data")

# Try to find an xlsx in data/
_candidates = glob.glob(os.path.join(DATA_DIR, "*.xlsx"))
EXCEL_PATH = next((p for p in _candidates if p and os.path.exists(p)), None)
if EXCEL_PATH is None:
    for name in ("Crop_recommendation.xlsx", "crop_data.xlsx", "Crop_recommendation (1).xlsx"):
        p = os.path.join(DATA_DIR, name)
        if os.path.exists(p):
            EXCEL_PATH = p
            break

_DF_CACHE: Optional[pd.DataFrame] = None

def _load_df() -> pd.DataFrame:
    global _DF_CACHE
    if _DF_CACHE is not None:
        return _DF_CACHE
    if not EXCEL_PATH:
        raise FileNotFoundError("Excel file not found in data/ directory.")
    df = pd.read_excel(EXCEL_PATH)
    # Normalize column names
    df.columns = (
        df.columns.str.strip()
        .str.replace("°", "C", regex=False)
        .str.replace(r"\s+", "_", regex=True)
        .str.lower()
    )
    _DF_CACHE = df
    return df

# ---------- Normalization & fuzzy helpers ----------
_SYNONYMS = {
    "regur": "black",
    "black cotton soil": "black",
    "black soil": "black",
    "alluvium": "alluvial",
    "alluvial soil": "alluvial",
    "loam": "loamy",
    "sandyloam": "sandy loam",
    "sandy-loam": "sandy loam",
    "sandy loam": "sandy loam",
    "clayey": "clay",
    "red soil": "red",
    "red-soil": "red",
}

def _normalize_soil_name(s: Optional[str]) -> str:
    """Lowercase, remove punctuation/stopwords, map synonyms, collapse spaces."""
    if not s:
        return ""
    s0 = str(s).strip().lower()
    # common tokens to remove
    s0 = re.sub(r"\b(soil|type|soils)\b", " ", s0)
    s0 = re.sub(r"[^a-z0-9\s\-]", " ", s0)
    s0 = s0.replace("/", " ").replace("_", " ").replace(",", " ")
    s0 = re.sub(r"\s+", " ", s0).strip()
    # map synonyms by exact phrase first
    for k, v in _SYNONYMS.items():
        if k in s0:
            # replace occurrences of the phrase with canonical term
            s0 = s0.replace(k, v)
    s0 = re.sub(r"\s+", " ", s0).strip()
    return s0

def _token_similarity(a: str, b: str) -> float:
    """Simple token-overlap similarity ratio between 0..1."""
    if not a or not b:
        return 0.0
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return 0.0
    inter = ta.intersection(tb)
    # ratio relative to smaller set (gives match if nearly contained)
    denom = max(len(ta), len(tb))
    return len(inter) / denom

# ---------- Public DB helpers ----------
def get_soils_for_state(state: str) -> List[str]:
    """Return list of soil types (Title Case) for the given state from the DB."""
    try:
        if not state:
            return []
        df = _load_df()
        if "state" not in df.columns or "soil_type" not in df.columns:
            return []
        s = str(state).strip().lower()
        subset = df[df["state"].astype(str).str.lower() == s]
        soils = subset["soil_type"].dropna().astype(str).str.strip().unique().tolist()
        # normalize spacing and title-case for display
        cleaned = []
        for x in soils:
            x0 = str(x).strip()
            if x0:
                cleaned.append(x0.title())
        return cleaned
    except Exception:
        return []

def check_soil_exists(state: str, soil_type: str) -> bool:
    """
    Robust check whether soil_type exists for state in DB.
    Uses normalization, synonyms, substring and token overlap checks.
    """
    try:
        if not state or not soil_type:
            return False
        soils = get_soils_for_state(state)
        if not soils:
            return False

        user_norm = _normalize_soil_name(soil_type)
        if not user_norm:
            return False

        # check exact / substring match first
        for db_soil in soils:
            db_norm = _normalize_soil_name(db_soil)
            if not db_norm:
                continue
            # direct equivalence
            if db_norm == user_norm:
                return True
            # substring either way
            if user_norm in db_norm or db_norm in user_norm:
                return True

        # token similarity fallback
        for db_soil in soils:
            db_norm = _normalize_soil_name(db_soil)
            sim = _token_similarity(user_norm, db_norm)
            if sim >= 0.5:
                return True

        return False
    except Exception:
        return False

# ---------- crop query helpers (unchanged but kept robust) ----------
def _parse_temp_range_cell(cell: Any):
    """Parse typical temp range strings, return (min, max) floats or (None, None)."""
    try:
        if cell is None:
            return (None, None)
        s = str(cell)
        s = s.replace("°", "").replace("C", "").replace("c", "")
        s = s.replace("–", "-").replace("—", "-").replace("to", "-").replace(",", " ")
        parts = [p.strip() for p in s.split("-") if p.strip() != ""]
        if len(parts) >= 2:
            try:
                return float(parts[0]), float(parts[1])
            except:
                return (None, None)
        try:
            v = float(s.strip())
            return (v, v)
        except:
            return (None, None)
    except Exception:
        return (None, None)

def query_crops(state: str, soil_type: str, temperature: Optional[float]=None, season: Optional[str]=None) -> Dict[str, Any]:
    """
    Query DB with state + soil_type + optional season + optional temperature filtering.
    Returns {"crops": [..], "no_match": bool}
    """
    try:
        df = _load_df()
        if "state" not in df.columns or "soil_type" not in df.columns:
            return {"crops": [], "no_match": True}

        mask = (df["state"].astype(str).str.lower() == str(state).lower())
        if soil_type:
            # match robustly: use normalized compare per-row
            def row_matches_soil(val):
                return _normalize_soil_name(val) == _normalize_soil_name(soil_type)
            mask = mask & df["soil_type"].apply(lambda v: row_matches_soil(v))
        if season and "season" in df.columns:
            mask = mask & (df["season"].astype(str).str.lower() == str(season).lower())

        filtered = df[mask]
        # temperature filtering if possible
        if temperature is not None and not filtered.empty:
            temp_cols = [c for c in filtered.columns if "temperature_range" in c]
            if temp_cols:
                rows = []
                for _, row in filtered.iterrows():
                    matched = False
                    for tc in temp_cols:
                        lo, hi = _parse_temp_range_cell(row.get(tc))
                        if lo is not None and hi is not None and lo <= float(temperature) <= hi:
                            matched = True
                            break
                    if matched:
                        rows.append(row)
                if rows:
                    filtered = pd.DataFrame(rows)

        if filtered.empty:
            return {"crops": [], "no_match": True}

        crops = []
        for _, row in filtered.iterrows():
            for c in ("option_1", "option_2", "option_3"):
                if c in row and pd.notna(row[c]):
                    crops.append(str(row[c]).strip())
        # remove duplicates but preserve order
        seen = set(); out = []
        for x in crops:
            if x not in seen:
                seen.add(x); out.append(x)
        return {"crops": out, "no_match": False}
    except Exception as e:
        print("excel_service.query_crops error:", e)
        return {"crops": [], "no_match": True}

def query_crops_for_soil(soil_type: str, temperature: Optional[float]=None, season: Optional[str]=None, limit: int = 3) -> List[str]:
    """
    Search the entire DB (ignore state) for crops matching soil_type.
    Used for "if you truly have X soil" global recommendations.
    """
    try:
        if not soil_type:
            return []
        df = _load_df()
        if "soil_type" not in df.columns:
            return []
        mask = df["soil_type"].apply(lambda v: _normalize_soil_name(v) == _normalize_soil_name(soil_type))
        if season and "season" in df.columns:
            mask = mask & (df["season"].astype(str).str.lower() == str(season).lower())
        filtered = df[mask]
        # temperature filter
        if temperature is not None and not filtered.empty:
            temp_cols = [c for c in filtered.columns if "temperature_range" in c]
            if temp_cols:
                rows = []
                for _, row in filtered.iterrows():
                    matched = False
                    for tc in temp_cols:
                        lo, hi = _parse_temp_range_cell(row.get(tc))
                        if lo is not None and hi is not None and lo <= float(temperature) <= hi:
                            matched = True
                            break
                    if matched:
                        rows.append(row)
                if rows:
                    filtered = pd.DataFrame(rows)

        if filtered.empty:
            return []

        crops = []
        for _, row in filtered.iterrows():
            for c in ("option_1", "option_2", "option_3"):
                if c in row and pd.notna(row[c]):
                    crops.append(str(row[c]).strip())
                    if len(crops) >= limit:
                        break
            if len(crops) >= limit:
                break
        # remove duplicates but preserve order
        seen = set(); out = []
        for x in crops:
            if x not in seen:
                seen.add(x); out.append(x)
        return out[:limit]
    except Exception as e:
        print("excel_service.query_crops_for_soil error:", e)
        return []

def query_crops_for_soil_with_seasons(soil_type: str, temperature: Optional[float]=None, season: Optional[str]=None, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Return a list of dicts for the given soil_type across DB with optional season filter.
    Each dict: {"crop": "<name>", "season": "<season-string-or-empty>"}
    """
    out = []
    try:
        if not soil_type:
            return []
        df = _load_df()
        if "soil_type" not in df.columns:
            return []
        mask = df["soil_type"].apply(lambda v: _normalize_soil_name(v) == _normalize_soil_name(soil_type))
        if season and "season" in df.columns:
            mask = mask & (df["season"].astype(str).str.lower() == str(season).lower())
        filtered = df[mask]
        # temperature filtering similar to other functions
        if temperature is not None and not filtered.empty:
            temp_cols = [c for c in filtered.columns if "temperature_range" in c]
            if temp_cols:
                rows = []
                for _, row in filtered.iterrows():
                    matched = False
                    for tc in temp_cols:
                        lo, hi = _parse_temp_range_cell(row.get(tc))
                        if lo is not None and hi is not None and lo <= float(temperature) <= hi:
                            matched = True
                            break
                    if matched:
                        rows.append(row)
                if rows:
                    filtered = pd.DataFrame(rows)

        if filtered.empty:
            return []

        seen = set()
        for _, row in filtered.iterrows():
            for c in ("option_1", "option_2", "option_3"):
                if c in row and pd.notna(row[c]):
                    crop_name = str(row[c]).strip()
                    if crop_name and crop_name not in seen:
                        seen.add(crop_name)
                        season_val = None
                        if "season" in row and pd.notna(row["season"]):
                            season_val = str(row["season"]).strip()
                        out.append({"crop": crop_name, "season": season_val})
                        if len(out) >= limit:
                            break
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        print("excel_service.query_crops_for_soil_with_seasons error:", e)
        return []
