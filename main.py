# main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import uvicorn
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# services - adjust imports if your project layout differs
from services import soil_service, weather_service, date_service, excel_service, gemini_service, web_service

app = FastAPI(title="Agri Backend - MVP v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Backend is running"}

# Important: openapi_extra defines multipart/form-data schema so Swagger shows the form + file chooser
@app.post(
    "/recommend",
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "state": {"type": "string"},
                            "city": {"type": "string"},
                            "pincode": {"type": "string"},
                            "date": {"type": "string", "format": "date"},
                            "soil_type": {"type": "string"},
                            "query": {"type": "string"},
                            "soil_image": {"type": "string", "format": "binary"}
                        },
                        "required": ["state", "pincode", "date"]
                    }
                }
            }
        }
    },
)
async def recommend(request: Request):
    """
    Robust form handler:
      - Uses request.form() to avoid FastAPI UploadFile pre-validation issues (empty-string problem).
      - openapi_extra above makes Swagger show multipart/form-data and a file picker.
    """
    try:
        form = await request.form()

        # Read form fields (strings)
        state = (form.get("state") or "").strip()
        city = (form.get("city") or "").strip()
        pincode = (form.get("pincode") or "").strip()
        date_str = (form.get("date") or "").strip()
        soil_type = (form.get("soil_type") or "").strip() or None
        query = (form.get("query") or "").strip() or None

        # server-side required checks (pincode/date/state required per your design)
        if not state:
            raise HTTPException(status_code=400, detail="state is required")
        if not pincode:
            raise HTTPException(status_code=400, detail="pincode is required")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required (YYYY-MM-DD)")

        # Normalize soil_image (may be an UploadFile or a blank string)
        raw_file = form.get("soil_image")
        soil_image = None
        try:
            # starlette.datastructures.UploadFile exposes .filename and .file/.read
            if raw_file is not None and hasattr(raw_file, "filename") and raw_file.filename:
                soil_image = raw_file
            else:
                soil_image = None
        except Exception:
            soil_image = None

        # parse date and extract month name
        try:
            dt = datetime.fromisoformat(date_str)
        except Exception:
            # fallback to strict parse
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                raise HTTPException(status_code=400, detail="Date must be ISO format YYYY-MM-DD.")
        month_name = dt.strftime("%B")

        # season detection
        season = date_service.get_season_from_date(date_str)
        season_months = date_service.get_season_months(season)

        # weather (temperature)
        temperature = None
        weather_data = {}
        try:
            if hasattr(weather_service, "get_weather_by_pincode"):
                weather_data = weather_service.get_weather_by_pincode(pincode) or {}
                temperature = weather_data.get("temperature") or weather_data.get("temp")
            elif hasattr(weather_service, "get_temperature_by_pincode"):
                temperature = weather_service.get_temperature_by_pincode(pincode)
                weather_data = {"temperature": temperature}
            else:
                weather_data = {}
        except Exception:
            weather_data = {}
            temperature = None

        # soil detection (pass state so the service can verify against DB)
        soil_result = await soil_service.get_soil_type_async(
            pincode=pincode,
            state=state,
            city=city,
            provided_soil_type=soil_type,
            soil_image=soil_image
        )

        # defensive: ensure dict shape
        if not isinstance(soil_result, dict):
            soil_result = {"soil_type": soil_result or "Unknown", "source": "fallback", "details": {}, "verified": False, "expected_soils": []}
        final_soil_type = soil_result.get("soil_type", "Unknown")

        # query DB for crops
        crops_info = excel_service.query_crops(state=state, soil_type=final_soil_type, temperature=temperature, season=season)

        # determine confirmed flag: soil_service can set verified, otherwise check DB
        verified_flag = bool(soil_result.get("verified", False))
        if not verified_flag and final_soil_type:
            try:
                verified_flag = excel_service.check_soil_exists(state, final_soil_type)
            except Exception:
                verified_flag = verified_flag

        # build verification_context only if not confirmed
        expected = soil_result.get("expected_soils") or excel_service.get_soils_for_state(state) or []
        verification_context = None
        if not verified_flag:
            if expected:
                verification_context = f"According to our data, we could not find an exact match for {final_soil_type} in {state}. Common soils in {state}: {', '.join(expected)}."
            else:
                # try a brief web snippet if available
                try:
                    web_snip = web_service.get_prevalent_soils(state)
                except Exception:
                    web_snip = None
                if web_snip:
                    first = web_snip.split(".")[0]
                    verification_context = f"According to our data, we could not find an exact match for {final_soil_type} in {state}. {first}."
                else:
                    verification_context = f"According to our data, we could not find an exact match for {final_soil_type} in {state}."

        # call gemini_service.generate_advice (gemini_service will fallback deterministically if needed)
        advice = gemini_service.generate_advice(
            soil_info=soil_result,
            weather=weather_data,
            season=season,
            season_months=season_months,
            crops=crops_info,
            query=query,
            state=state,
            verification_context=verification_context,
            farmer_reported_soil=(soil_type if soil_type else None),
            confirmed=verified_flag,
            month_name=month_name,
            excel_service=excel_service
        )

        response = {
            "soil_type_detected": final_soil_type,
            "soil_details": soil_result,
            "season": season,
            "season_months": season_months,
            "weather": {"temperature": temperature, "month": month_name},
            "recommended_crops": crops_info.get("crops") if isinstance(crops_info, dict) else crops_info,
            "no_db_match": crops_info.get("no_match") if isinstance(crops_info, dict) else False,
            "advice": advice
        }
        return JSONResponse(content=response)

    except HTTPException:
        raise
    except Exception as e:
        # return error for debugging; change to generic message for production
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
