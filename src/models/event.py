from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
import datetime
import uuid

Base = declarative_base()

class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text)
    date = Column(DateTime, default=datetime.datetime.utcnow)
    location = Column(String)
    edit_token = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    
