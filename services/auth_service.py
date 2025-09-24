# services/auth_service.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext

# These imports will now work correctly because main.py fixed the system path
import models, schemas, database

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.post("/register")
def register_user(request: schemas.RegisterRequest, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.username == request.username).first()
    if user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Username already registered")
    
    hashed_pw = pwd_context.hash(request.password)
    new_user = models.User(username=request.username, hashed_password=hashed_pw)
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {"message": f"User '{new_user.username}' created successfully."}

@router.post("/login")
def login_user(request: schemas.LoginRequest, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.username == request.username).first()
    if not user or not pwd_context.verify(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    history_records = db.query(models.ChatHistory).filter(models.ChatHistory.user_id == user.id).order_by(models.ChatHistory.timestamp.desc()).all()
    
    return {
        "message": "Login successful",
        "username": user.username,
        "history": history_records
    }