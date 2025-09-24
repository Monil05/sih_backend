from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.join(BASE_DIR, 'farmers.db')}"

# Engine and Base for all models — do NOT import models here to avoid circular imports
engine = create_engine(
    SQLITE_PATH,
    connect_args={"check_same_thread": False} if SQLITE_PATH.startswith("sqlite") else {},
    future=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()

# Dependency for FastAPI endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()