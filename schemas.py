"""
Database Schemas for Smart Access System - Facilities Management

Each Pydantic model represents a collection in MongoDB. The collection
name is the lowercase of the class name.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

class Facility(BaseModel):
    """
    Facilities collection schema
    Collection name: "facility"
    """
    name: str = Field(..., description="Facility display name")
    code: str = Field(..., description="Short code/identifier (unique)")
    location: Optional[str] = Field(None, description="Location / Floor detail")
    capacity: Optional[int] = Field(None, description="Optional capacity for information only")
    type: Literal[
        "meeting_room",
        "discussion_room",
        "banquet_hall",
        "gym",
        "training_centre",
        "studio",
        "badminton_court",
        "multipurpose_court",
        "football_field",
        "netball_court"
    ]
    is_active: bool = True

class Booking(BaseModel):
    """
    Bookings collection schema
    Collection name: "booking"
    """
    facility_id: str = Field(..., description="MongoDB ObjectId (string) of facility")
    facility_code: str = Field(..., description="Duplicate of code for quick lookup")
    user_name: str
    user_email: str
    purpose: Optional[str] = None
    date: str = Field(..., description="ISO date YYYY-MM-DD")
    start_time: str = Field(..., description="HH:MM 24h")
    end_time: str = Field(..., description="HH:MM 24h")
    status: Literal["pending", "approved", "rejected", "cancelled", "no_show"] = "pending"
    access_code: Optional[str] = Field(None, description="Code used at entry gates")
    checked_in_at: Optional[datetime] = None

class AdminAction(BaseModel):
    action: Literal["approve", "reject"]
    note: Optional[str] = None
