import re
from fastapi import APIRouter, Form, File, UploadFile, HTTPException
from typing import Optional
import pandas as pd
import aiohttp
import json

from services.gemini_service import ask_gemini
from services.excel_service import get_crop_recommendations
from services.web_service import search_web  # uses DuckDuckGo

router = APIRouter()

# Load your Excel DB once
EXCEL_FILE = "data/crop_recommendations.xlsx"
df = pd.read_excel(EXCEL_FILE)

# -------------------------------
# Utility: Clean text from Gemini
# -------------------------------
def clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove markdown **bold**
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    # Remove escaped quotes
    text = text.replace('\\"', '"')
    # Normalize spacing
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# -------------------------------
# Utility: Soil Verification
# -------------------------------
async def verify_soil(state: str, soil_input: Optional[str]) -> dict:
    state = state.strip().title()
    soil_input = soil_input.strip().title() if soil_input else None

    # 1. Check Excel DB
    state_rows = df[df['State'].str.lower() == state.lower()]
    if not state_rows.empty and soil_input:
        db_soils = state_rows['Soil_Type'].str.title().unique().tolist()
        if soil_input in db_soils:
            return {"soil_type": soil_input, "source": "db", "verified": True}
        else:
            # mismatch, record available soils
            return {"soil_type": soil_input, "source": "db_mismatch", "verified": False, "db_soils": db_soils}

    # 2. Check SoilGrids API
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://rest.soilgrids.org/query?lon=75.0&lat=31.6"  # demo near Punjab-Amritsar
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # For simplicity just extract a texture class if exists
                    texture = data.get("properties", {}).get("soil_class", "Unknown")
                    return {"soil_type": texture.title(), "source": "soilgrids", "verified": False}
    except Exception:
        pass

    # 3. Fallback: Web lookup
    if soil_input:
        query = f"common soil types in {state} India"
        web_data = await search_web(query)
        if web_data:
            return {"soil_type": soil_input, "source": "web_lookup", "verified": False, "web_info": web_data}

    # 4. Last fallback: Unknown
    return {"soil_type": soil_input or "Unknown", "source": "unknown", "verified": False}

# -------------------------------
# Main Recommend Endpoint
# -------------------------------
@router.post("/recommend")
async def recommend(
    state: str = Form(...),
    city: Optional[str] = Form(None),
    pincode: Optional[str] = Form(None),
    date: str = Form(...),
    soil_type: Optional[str] = Form(None),
    soil_image: Optional[UploadFile] = File(None),
    query: Optional[str] = Form(None),
):
    # Step 1: Verify soil
    soil_details = await verify_soil(state, soil_type)

    # Step 2: Lookup crops in DB (Excel)
    crops = []
    if soil_details.get("verified"):
        crops = get_crop_recommendations(state, soil_details["soil_type"])

    # Step 3: Weather stub (extend if you integrate weather API)
    weather = {
        "temperature": 29.97,
        "ph": None,
        "moisture": None
    }

    # Step 4: Build context for Gemini
    base_prompt = f"""
    Farmer is in {state}, soil: {soil_details['soil_type']} (source: {soil_details['source']}).
    Season: based on date {date}, assume Kharif if June-Oct else Rabi.
    Temperature ~{weather['temperature']}°C.

    Recommended crops from DB: {crops if crops else "None"}.

    If no pH and moisture data, suggest general fertilizers (e.g., farmyard manure, compost, cow dung, NPK).
    """

    gemini_response = await ask_gemini(base_prompt)

    return {
        "soil_type_detected": soil_details["soil_type"],
        "soil_details": soil_details,
        "season": "Kharif" if "06" <= date.split("-")[1] <= "10" else "Rabi",
        "weather": weather,
        "recommended_crops": crops,
        "advice": clean_text(gemini_response),
    }
