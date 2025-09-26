from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User, ChatHistory
from datetime import datetime

router = APIRouter(prefix="/chat", tags=["chat"])

# Get chat history by username
@router.get("/history/{username}")
def get_chat_history(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    history = db.query(ChatHistory).filter(ChatHistory.user_id == user.id)\
                                    .order_by(ChatHistory.timestamp.asc()).all()
    return [
        {"query": h.query, "response": h.response, "timestamp": h.timestamp} 
        for h in history
    ]

# Save a chat message
@router.post("/save")
def save_chat(username: str, query: str, response: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        # Optionally, create the user automatically
        user = User(username=username, hashed_password="")  # empty password if not used
        db.add(user)
        db.commit()
        db.refresh(user)

    chat = ChatHistory(user_id=user.id, query=query, response=response, timestamp=datetime.utcnow())
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return {"status": "success", "chat_id": chat.id}
