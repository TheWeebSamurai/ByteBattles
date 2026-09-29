from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from shared.core import SessionLocal

from config import DB_URL

class Database:
    def __init__(self):
        self.SessionLocal = SessionLocal

    @contextmanager
    def session(self):
        db: Session = self.SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
