# services/recommendation_service.py
import re
from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Depends, status
from typing import Optional
from sqlalchemy.orm import Session

# These imports will now work correctly
import models, schemas, database
from services import gemini_service, excel_service, web_service, soil_service, weather_service, date_service

router = APIRouter(
    prefix="/farm",
    tags=["Farming Recommendations"]
)

@router.post("/recommend")
async def recommend(
    state: str = Form(...),
    username: str = Form(...),
    date: str = Form(...),
    city: Optional[str] = Form(None),
    pincode: Optional[str] = Form(None),
    soil_type: Optional[str] = Form(None),
    soil_image: Optional[UploadFile] = File(None),
    query: Optional[str] = Form(None),
    db: Session = Depends(database.get_db)
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # --- This is your existing orchestration logic ---
    soil_details = await soil_service.verify_soil(state, soil_type, pincode, soil_image)
    final_soil_type = soil_details.get("soil_type", "Unknown")
    verified_flag = soil_details.get("verified", False)
    
    weather_data = weather_service.get_weather_and_soil_details(pincode)
    temperature = weather_data.get('temperature')
    month_name = date_service.get_month_name(date)
    season = date_service.get_season_from_date(date)
    season_months = date_service.get_season_months(season)

    crops_info = excel_service.query_crops(state, final_soil_type, temperature, season)

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

    # --- Database Integration ---
    new_chat = models.ChatHistory(
        user_id=user.id,
        query=query if query else "General Recommendation",
        response=advice
    )
    db.add(new_chat)
    db.commit()

    # Return the final advice and other details
    return {
        "soil_type_detected": final_soil_type,
        "soil_details": soil_details,
        "season": season,
        "weather": weather_data,
        "recommended_crops": crops_info,
        "advice": advice
    }