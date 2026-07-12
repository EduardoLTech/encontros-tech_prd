from pydantic import BaseModel
from typing import List, Optional
import datetime

class EventBase(BaseModel):
    title: str
    description: Optional[str] = None
    date: datetime.datetime
    location: str
    technologies: List[str] = []

class EventCreate(EventBase):
    pass

class EventUpdate(EventBase):
    pass

class Event(EventBase):
    id: int
    edit_token: str

    class Config:
        from_attributes = True
