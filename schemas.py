from pydantic import BaseModel
from datetime import datetime

class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class QueryRequest(BaseModel):
    username: str
    query: str

class ChatResponse(BaseModel):
    query: str
    response: str
    time: datetime