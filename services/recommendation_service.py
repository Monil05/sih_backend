# ...existing code...
import re
import logging
from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Depends, status
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

import models, database
from services import gemini_service, excel_service, web_service, soil_service, weather_service, date_service

router = APIRouter(
    prefix="/farm",
    tags=["Farming Recommendations"]
)

logger = logging.getLogger("recommendation_service")

@router.post("/recommend")
async def recommend(
    state: str = Form(...),
    username: str = Form(...),
    date: str = Form(...),
    city: Optional[str] = Form(None),
    pincode: str = Form(...),
    soil_type: Optional[str] = Form(None),
    soil_image: Optional[UploadFile] = File(None),
    query: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
) -> Dict[str, Any]:
    """
    - pincode required (6 digits).
    - If farmer provides soil_type -> use it.
    - If no soil_type and image provided -> try local image classifier first (gemini_service.classify_soil_image).
      - If classifier returns a soil, use it (skip passing image to soil_service).
      - If classifier returns None, pass the image to soil_service.verify_soil so it can run its own checks.
    - Weather data always fetched via weather_service.get_weather_and_soil_details(pincode).
    """
    pincode = (pincode or "").strip()
    if not re.match(r"^\d{6}$", pincode):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pincode is required and must be 6 digits")

    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check whether farmer provided meaningful soil_type
    unknown_tokens = ("don't know", "dont know", "unknown", "na", "n/a", "")
    provided = (soil_type.strip() if soil_type and str(soil_type).strip() != "" else None)
    provided_is_meaningful = bool(provided and str(provided).strip().lower() not in unknown_tokens)

    image_inferred: Optional[str] = None
    passed_image_to_service = None

    # If farmer didn't give soil type and provided an image, try local classifier
    if not provided_is_meaningful and soil_image is not None:
        try:
            # read bytes from UploadFile
            img_bytes = None
            try:
                img_bytes = await soil_image.read()
            except Exception:
                # fallback to file.read for resilience
                try:
                    img_bytes = soil_image.file.read()
                except Exception:
                    img_bytes = None
            if img_bytes:
                try:
                    image_inferred = gemini_service.classify_soil_image(img_bytes)
                except Exception as e:
                    logger.debug("image classifier error: %s", e)
                    image_inferred = None
                # reset pointer so downstream services can read if needed
                try:
                    await soil_image.seek(0)
                except Exception:
                    try:
                        soil_image.file.seek(0)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("unexpected image read error: %s", e)
            image_inferred = None

    # If classifier gave a value, use that as reported soil; otherwise allow soil_service to use the image
    reported_soil_for_verify = provided if provided_is_meaningful else image_inferred
    pass_image_to_service = None if image_inferred else soil_image

    # Call soil verification/inference
    try:
        soil_details = await soil_service.verify_soil(
            state=state,
            reported_soil=reported_soil_for_verify,
            pincode=pincode,
            soil_image=pass_image_to_service,
            city=city
        )
    except Exception as e:
        logger.exception("soil_service.verify_soil failed: %s", e)
        soil_details = {"soil_type": "Unknown", "source": "error", "details": {}, "verified": False, "expected_soils": []}

    # If we inferred via image locally, ensure result reflects that
    if image_inferred:
        # prefer the classifier if soil_service didn't disagree strongly
        try:
            soil_details.setdefault("details", {})
            soil_details["details"].setdefault("image_guess", image_inferred)
            # if service returned unknown or farmer_input_unverified, reflect image source
            src = soil_details.get("source", "") or ""
            if src in ("", "farmer_input_unverified", "fallback", "error") or soil_details.get("soil_type") in (None, "Unknown"):
                soil_details["soil_type"] = image_inferred
                soil_details["source"] = "image"
                soil_details["verified"] = False
        except Exception:
            pass

    final_soil_type = soil_details.get("soil_type", "Unknown")
    verified_flag = bool(soil_details.get("verified", False))

    # Weather: try to populate temperature/humidity/conditions/ph/moisture via weather_service
    try:
        weather_data = weather_service.get_weather_and_soil_details(pincode)
    except Exception as e:
        logger.exception("weather_service failed: %s", e)
        weather_data = {"temperature": None, "humidity": None, "conditions": None, "ph": None, "moisture": None, "source": "error"}

    temperature = weather_data.get("temperature")
    month_name = date_service.get_month_name(date)
    season = date_service.get_season_from_date(date)
    season_months = date_service.get_season_months(season)

    # Query crops
    try:
        crops_info = excel_service.query_crops(state, final_soil_type, temperature, season)
    except Exception as e:
        logger.debug("excel_service.query_crops failed: %s", e)
        crops_info = {"crops": [], "no_match": True}

    # Generate advice
    try:
        advice = gemini_service.generate_advice(
            soil_info=soil_details,
            weather=weather_data,
            season=season,
            season_months=season_months,
            crops=crops_info,
            query=query,
            state=state,
            farmer_reported_soil=soil_type,
            confirmed=verified_flag,
            month_name=month_name,
            excel_service=excel_service
        )
    except Exception as e:
        logger.exception("gemini_service.generate_advice failed: %s", e)
        advice = "Could not generate AI advice at this time. See soil_details and recommended_crops for guidance."

    # Persist chat/history (best-effort)
    try:
        new_chat = models.ChatHistory(
            user_id=user.id,
            query=query if query else "General Recommendation",
            response=advice
        )
        db.add(new_chat)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    return {
        "soil_type_detected": final_soil_type,
        "soil_details": soil_details,
        "image_inferred": image_inferred,
        "season": season,
        "season_months": season_months,
        "weather": weather_data,
        "recommended_crops": crops_info,
        "advice": advice
    }
# ...existing code...