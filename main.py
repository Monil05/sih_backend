# main.py
import sys
import os
# Add the project's root directory to the Python path to fix all import errors
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

# Import your routers and the database engine
from services import auth_service, recommendation_service
import models, database

# Load .env and create database tables if they don't exist
load_dotenv()
# CORRECTED LINE: Use 'database.Base' instead of 'models.Base'
database.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title='Agri Backend v2 - Final Production')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

# Include the routers from your services
app.include_router(auth_service.router)
app.include_router(recommendation_service.router)


@app.get("/")
async def root():
    return {"message": "Backend is running and all services are connected."}

if __name__ == '__main__':
    uvicorn.run('main:app', host='0.0.0.0', port=int(os.environ.get("PORT", 8000)), reload=True)