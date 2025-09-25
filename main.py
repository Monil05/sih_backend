# ...existing code...
import os
import sys
from dotenv import load_dotenv

# Load .env first so modules that read env at import time get values
load_dotenv()

# Add the project's root directory to the Python path to fix import errors
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import your routers and the database engine AFTER .env is loaded
from services import auth_service, recommendation_service, weather_service
import database

# Create database tables if they don't exist
database.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title='Agri Backend v2 - Final Production')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

# simple root to avoid 404 on "/"
@app.get("/", include_in_schema=False)
def root():
    return {"status": "ok", "message": "Agri Backend running"}

# health endpoint: tries to call optional check helpers in weather_service if present
@app.get("/health")
def health():
    res = {"app": "ok"}
    try:
        check_open = getattr(weather_service, "check_openweather_key", None)
        if callable(check_open):
            res["openweather"] = check_open()
        else:
            res["openweather"] = {"ok": None, "message": "no check_openweather_key() available"}
    except Exception as e:
        res["openweather"] = {"ok": False, "error": str(e)}
    try:
        check_bhu = getattr(weather_service, "check_bhuvan", None)
        if callable(check_bhu):
            res["bhuvan"] = check_bhu()
        else:
            res["bhuvan"] = {"ok": None, "message": "no check_bhuvan() available"}
    except Exception as e:
        res["bhuvan"] = {"ok": False, "error": str(e)}
    return res

# Include the routers from your services
app.include_router(auth_service.router)
app.include_router(recommendation_service.router)
# ...existing code...