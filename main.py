import os
from datetime import datetime, timedelta, date
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import Facility, Booking, AdminAction
from bson import ObjectId
import smtplib
from email.mime.text import MIMEText

app = FastAPI(title="Smart Access - Facilities Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# Utilities
# -------------------------------

def oid_str(o: Any) -> str:
    try:
        return str(o)
    except Exception:
        return o


def to_local_dt(date_str: str, time_str: str) -> datetime:
    # date: YYYY-MM-DD, time HH:MM
    y, m, d = [int(x) for x in date_str.split("-")]
    hh, mm = [int(x) for x in time_str.split(":")]
    return datetime(y, m, d, hh, mm)


def overlaps(s1: str, e1: str, s2: str, e2: str) -> bool:
    a1 = to_local_dt("2000-01-01", s1)
    b1 = to_local_dt("2000-01-01", e1)
    a2 = to_local_dt("2000-01-01", s2)
    b2 = to_local_dt("2000-01-01", e2)
    return a1 < b2 and a2 < b1


def send_email(to_email: str, subject: str, body: str):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "0") or 0)
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    from_email = os.getenv("FROM_EMAIL", smtp_user or "noreply@example.com")

    if not smtp_host or not smtp_port:
        print("[EMAIL LOG] To:", to_email)
        print("Subject:", subject)
        print(body)
        return

    try:
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, [to_email], msg.as_string())
    except Exception as e:
        print("[EMAIL ERROR]", e)


# -------------------------------
# Data seeding
# -------------------------------

def build_default_facilities() -> List[Facility]:
    items: List[Facility] = []
    # Meeting Rooms (10)
    for i in range(10):
        items.append(Facility(name="Meeting Room, Mezzanine Floor", code=f"MR-{i+1}", type="meeting_room", location="Mezzanine Floor"))
    # Discussion Rooms (11)
    for i in range(11):
        items.append(Facility(name="Discussion Room, Persada Tower", code=f"DR-{i+1}", type="discussion_room", location="Selected Floors - Persada Tower"))
    # Banquet & Gym (1 each)
    items.append(Facility(name="Banquet Hall", code="BH-1", type="banquet_hall", location="Convention Wing"))
    items.append(Facility(name="Gymnasium", code="GYM-1", type="gym", location="Level 2"))
    # Training Centre (6)
    for i in range(6):
        items.append(Facility(name="PLUS Training Centre", code=f"PTC-{i+1}", type="training_centre", location="Training Centre"))
    # Studio (1)
    items.append(Facility(name="PLUS Studio", code="STUDIO-1", type="studio", location="Media Wing"))
    # Badminton Courts (2)
    for i in range(2):
        items.append(Facility(name="Badminton Court", code=f"BC-{i+1}", type="badminton_court", location="Sports Complex"))
    # Multipurpose Courts (2)
    for i in range(2):
        items.append(Facility(name="Multipurpose Court", code=f"MPC-{i+1}", type="multipurpose_court", location="Sports Complex"))
    # Football + Netball
    items.append(Facility(name="Persada Football Field", code="PFF-1", type="football_field", location="Outdoor"))
    items.append(Facility(name="Netball Court", code="NC-1", type="netball_court", location="Sports Complex"))
    return items

DEFAULT_FACILITIES: List[Facility] = build_default_facilities()


@app.post("/api/facilities/seed")
def seed_facilities():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    count = db["facility"].count_documents({})
    if count > 0:
        return {"message": "Facilities already seeded", "count": count}
    inserted = 0
    for fac in DEFAULT_FACILITIES:
        create_document("facility", fac)
        inserted += 1
    return {"message": "Facilities seeded", "count": inserted}


# -------------------------------
# Facilities & Availability
# -------------------------------

@app.get("/")
def root():
    return {"message": "Smart Access Facilities API"}


@app.get("/api/facilities")
def list_facilities() -> List[Dict[str, Any]]:
    facilities = get_documents("facility")
    out = []
    for f in facilities:
        f["_id"] = oid_str(f.get("_id"))
        out.append(f)
    return out


@app.get("/api/availability")
def availability(facility_code: str = Query(...), date_str: str = Query(..., alias="date")):
    # find facility
    fac = db["facility"].find_one({"code": facility_code})
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found")
    # get bookings for that date which are not cancelled/rejected
    bookings = list(db["booking"].find({
        "facility_code": facility_code,
        "date": date_str,
        "status": {"$in": ["pending", "approved"]}
    }))
    intervals = [{
        "start": b["start_time"],
        "end": b["end_time"],
        "status": b["status"]
    } for b in bookings]

    fully_occupied = False
    # consider full day 08:00-22:00 for all facilities as operation hours
    open_t, close_t = "08:00", "22:00"
    # naive full-day detection: if one booking covers full range OR sum covers all 14 hours with no gaps.
    def minutes(t: str) -> int:
        h, m = [int(x) for x in t.split(":")]
        return h*60 + m

    covered = [0] * (minutes(close_t) - minutes(open_t))
    for b in bookings:
        s = max(minutes(b["start_time"]), minutes(open_t)) - minutes(open_t)
        e = min(minutes(b["end_time"]), minutes(close_t)) - minutes(open_t)
        for i in range(max(0, s), max(0, e)):
            if 0 <= i < len(covered):
                covered[i] = 1
    if covered and all(covered):
        fully_occupied = True

    return {
        "facility_code": facility_code,
        "date": date_str,
        "unavailable": intervals,
        "fully_occupied": fully_occupied,
        "hours": {"open": open_t, "close": close_t}
    }


# -------------------------------
# Booking
# -------------------------------

class CreateBooking(BaseModel):
    facility_code: str
    user_name: str
    user_email: str
    purpose: Optional[str] = None
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str  # HH:MM


def notify_admin_new_booking(data: Dict[str, Any]):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    subject = f"New booking request: {data['facility_code']} on {data['date']}"
    body = f"""
    <h3>New Booking Request</h3>
    <p><b>Facility:</b> {data['facility_code']}</p>
    <p><b>Date:</b> {data['date']} {data['start_time']}-{data['end_time']}</p>
    <p><b>User:</b> {data['user_name']} ({data['user_email']})</p>
    <p><b>Purpose:</b> {data.get('purpose','-')}</p>
    <p>Please review in the admin panel.</p>
    """
    send_email(admin_email, subject, body)


def notify_user_status(email: str, status: str, facility_code: str, date_str: str, start: str, end: str, access_code: Optional[str]):
    subject = f"Your booking has been {status}"
    code_html = f"<p><b>Access code:</b> {access_code}</p>" if access_code else ""
    body = f"""
    <p>Your booking request for <b>{facility_code}</b> on <b>{date_str} {start}-{end}</b> has been <b>{status}</b>.</p>
    {code_html}
    """
    send_email(email, subject, body)


@app.post("/api/bookings")
def create_booking(payload: CreateBooking, background_tasks: BackgroundTasks):
    fac = db["facility"].find_one({"code": payload.facility_code})
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found")

    # Time validation
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="Invalid time range")

    # Check overlaps (pending or approved only)
    existing = list(db["booking"].find({
        "facility_code": payload.facility_code,
        "date": payload.date,
        "status": {"$in": ["pending", "approved"]}
    }))
    for b in existing:
        if overlaps(payload.start_time, payload.end_time, b["start_time"], b["end_time"]):
            raise HTTPException(status_code=409, detail="Time slot not available")

    booking = Booking(
        facility_id=str(fac.get("_id")),
        facility_code=payload.facility_code,
        user_name=payload.user_name,
        user_email=payload.user_email,
        purpose=payload.purpose,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        status="pending"
    )
    booking_id = create_document("booking", booking)

    background_tasks.add_task(notify_admin_new_booking, {**payload.model_dump(), "_id": booking_id})

    return {"message": "Booking created and pending approval", "booking_id": booking_id}


@app.get("/api/bookings/mine")
def my_bookings(email: str = Query(...)):
    rows = list(db["booking"].find({"user_email": email}).sort("date", 1))
    for r in rows:
        r["_id"] = oid_str(r["_id"])
    return rows


@app.get("/api/admin/bookings")
def admin_bookings():
    rows = list(db["booking"].find({}).sort([("date", 1), ("start_time", 1)]))
    for r in rows:
        r["_id"] = oid_str(r["_id"])
    return rows


@app.post("/api/bookings/{booking_id}/admin")
def admin_action(booking_id: str, action: AdminAction):
    try:
        _id = ObjectId(booking_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid booking id")

    b = db["booking"].find_one({"_id": _id})
    if not b:
        raise HTTPException(status_code=404, detail="Not found")

    if action.action == "approve":
        access_code = os.urandom(3).hex().upper()
        db["booking"].update_one({"_id": _id}, {"$set": {"status": "approved", "access_code": access_code}})
        notify_user_status(b["user_email"], "approved", b["facility_code"], b["date"], b["start_time"], b["end_time"], access_code)
        return {"message": "Approved"}
    else:
        db["booking"].update_one({"_id": _id}, {"$set": {"status": "rejected"}})
        notify_user_status(b["user_email"], "rejected", b["facility_code"], b["date"], b["start_time"], b["end_time"], None)
        return {"message": "Rejected"}


# -------------------------------
# Access control integration (check-in)
# -------------------------------

class CheckInPayload(BaseModel):
    access_code: str


@app.post("/api/bookings/{booking_id}/check-in")
def check_in(booking_id: str, payload: CheckInPayload):
    try:
        _id = ObjectId(booking_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid booking id")

    b = db["booking"].find_one({"_id": _id})
    if not b:
        raise HTTPException(status_code=404, detail="Not found")
    if b.get("status") != "approved":
        raise HTTPException(status_code=400, detail="Booking not approved")
    if b.get("access_code") != payload.access_code:
        raise HTTPException(status_code=403, detail="Invalid access code")

    db["booking"].update_one({"_id": _id}, {"$set": {"checked_in_at": datetime.utcnow()}})
    return {"message": "Check-in recorded"}


# -------------------------------
# No-show sweep (auto-cancel)
# -------------------------------

NO_SHOW_GRACE_MIN = int(os.getenv("NO_SHOW_GRACE_MIN", "15"))


def sweep_noshows():
    today = datetime.utcnow().date()
    # find approved bookings for today or earlier that have started and not checked-in
    rows = list(db["booking"].find({
        "status": "approved",
        "checked_in_at": {"$exists": False}
    }))
    now = datetime.utcnow()
    changed = 0
    for b in rows:
        b_date = datetime.strptime(b["date"], "%Y-%m-%d").date()
        start_dt_local = to_local_dt(b["date"], b["start_time"])  # assume server local
        if b_date <= today and now >= (start_dt_local + timedelta(minutes=NO_SHOW_GRACE_MIN)):
            db["booking"].update_one({"_id": b["_id"]}, {"$set": {"status": "no_show"}})
            changed += 1
    if changed:
        print(f"[SWEEP] Marked {changed} bookings as no_show")
    return changed


@app.get("/api/sweep")
def api_sweep():
    changed = sweep_noshows()
    return {"changed": changed}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected & Working"
            response["database_url"] = "✅ Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()
        else:
            response["database"] = "❌ Not Configured"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
