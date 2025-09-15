import os
import requests
from fastapi import FastAPI, Query ,WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from pydantic import BaseModel , validator
from datetime import datetime
from fastkml import kml
from shapely.geometry import Point, Polygon
from typing import List , Optional,Union,cast,Dict
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from shapely.wkt import loads as load_wkt
from shapely.geometry import Point
from geoalchemy2.functions import ST_GeomFromText
from twilio.rest import Client
import db_models, database
import asyncio

load_dotenv()
API_KEY = os.getenv("GEOAPIFY_API_KEY")

app = FastAPI()


# Twilio credentials from .env
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE")

twilio_client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

print(TWILIO_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE)

class EmergencyContact(BaseModel):
    """Emergency contact model"""
    name: Optional[str] = None
    phone: str
    email: Optional[str] = None
    relationship: Optional[str] = None

# User Schemas
class UserBase(BaseModel):
    user_name: str
    administration_id: int
    recent_alerts: Optional[str] = None
    emergency_contacts: Optional[List[Union[str, EmergencyContact]]] = None

    @validator('emergency_contacts')
    def validate_emergency_contacts(cls, v):
        if v is not None and len(v) > 3:
            raise ValueError('Maximum 3 emergency contacts allowed')
        return v

    @validator('user_name')
    def validate_user_name(cls, v):
        if not v or not v.strip():
            raise ValueError('User name cannot be empty')
        return v.strip()

class Location(BaseModel):
    lat: float
    lon: float
    user_id: int
    administration_id: int
    administration_name: str


class DeviceLocation(BaseModel):
    lat: float
    lon: float
    user_id: int     
    device_id: str    
    time: datetime

# ---- Administrations ----
class AdministrationCreate(BaseModel):
    administration_name: str

class AdministrationResponse(BaseModel):
    administration_id: int
    administration_name: str
    created_at: datetime

    class Config:
        from_attributes = True

# ---- Zones ----
class ZoneCreate(BaseModel):
    administration_id: int
    boundary: Optional[str] = None  
    danger_zone: Optional[str] = None
    path_zone: Optional[str] = None  

class ZoneResponse(BaseModel):
    id: int
    administration_id: int
    created_at: datetime

    class Config:
        from_attributes = True





class SweetSpotCreate(BaseModel):
    admin_id: int
    sweet_spot_name: str
    sweet_spot_zone: Optional[str] = None  

class SweetSpotResponse(BaseModel):
    sweet_spot_id: int
    admin_id: int
    sweet_spot_name: str
    created_at: datetime

    class Config:
        from_attributes = True


user_ws: Optional[WebSocket] = None
admin_ws: Optional[WebSocket] = None

latest_coords = None

@app.post("/device-alert/")
def device_alert(payload: DeviceLocation, db: Session = Depends(database.get_db)):
    # FETCH USER
    user = db.query(db_models.User).filter(db_models.User.user_id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # GET EMERGENCY CONTACTS (LIST OF STRINGS)
    contacts: List[str] = user.emergency_contacts or []
    if not contacts:
        return {"status": "no_contacts", "message": "No emergency contacts found"}

    # PREPARE SMS MESSAGE
    message_body = (
        f"🚨 SOS Alert 🚨\n"
        f"User: {user.user_name}\n"
        f"Device ID: {payload.device_id}\n"
        f"Location: https://www.google.com/maps?q={payload.lat},{payload.lon}\n"
        f"Time: {payload.time}"
    )

    # SEND SMS TO EACH CONTACT
    sent_numbers = []
    for phone_number in contacts:
        # ENSURE PHONE NUMBER HAS COUNTRY CODE
        if not phone_number.startswith("+"):
            phone_number = "+91" + phone_number  # default to India
        try:
            msg = twilio_client.messages.create(
                body=message_body,
                from_=TWILIO_PHONE,
                to=phone_number
            )
            sent_numbers.append(phone_number)
        except Exception as e:
            print(f"Failed to send SMS to {phone_number}: {e}")

    return {"status": "sent", "sent_to": sent_numbers}




# ---- Create User ----
@app.post("/users/")
def create_user(user: UserBase, db: Session = Depends(database.get_db)):
    # Check if administration exists
    admin = db.query(db_models.Administration).filter(
        db_models.Administration.administration_id == user.administration_id
    ).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Administration not found")

    db_user = db_models.User(
        user_name=user.user_name,
        administration_id=user.administration_id,
        recent_alerts=user.recent_alerts,
        emergency_contacts=user.emergency_contacts  # JSON directly
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return {
        "id": db_user.user_id,
        "user_name": db_user.user_name,
        "administration_id": db_user.administration_id,
        "recent_alerts": db_user.recent_alerts,
        "emergency_contacts": db_user.emergency_contacts,
        "created_at": db_user.created_at,
    }


# ---- Get User by ID ----
@app.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(database.get_db)):
    user = db.query(db_models.User).filter(db_models.User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": user.user_id,
        "user_name": user.user_name,
        "administration_id": user.administration_id,
        "recent_alerts": user.recent_alerts,
        "emergency_contacts": user.emergency_contacts,
        "created_at": user.created_at,
    }



@app.post("/send_coords")
async def send_coords(location: Location, db: Session = Depends(database.get_db)):
    global latest_coords
    latest_coords = location

    # run your check_point logic
    result = check_point(location, db)

    # if violation, push to user & admin
    if "error" not in result and result["alerts"][0] != "Safe":
        if user_ws:
            await user_ws.send_json(result)
        if admin_ws:
            await admin_ws.send_json(result)

    return {"status": "processed", "alerts": result["alerts"]}

# WebSocket endpoint for user
@app.websocket("/ws/user")
async def ws_user(websocket: WebSocket):
    global user_ws
    await websocket.accept()
    user_ws = websocket
    try:
        while True:
            await asyncio.sleep(1)  # just keep connection alive
    except WebSocketDisconnect:
        user_ws = None

# WebSocket endpoint for admin
@app.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket):
    global admin_ws
    await websocket.accept()
    admin_ws = websocket
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        admin_ws = None


@app.post("/sweet-spots/", response_model=SweetSpotResponse)
def create_sweet_spot(sweet_spot: SweetSpotCreate, db: Session = Depends(database.get_db)):
    # Check if administration exists
    admin = db.query(db_models.Administration).filter(
        db_models.Administration.administration_id == sweet_spot.admin_id
    ).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Administration not found")

    db_sweet_spot = db_models.SweetSpot(
        admin_id=sweet_spot.admin_id,
        sweet_spot_name=sweet_spot.sweet_spot_name
    )

    # Convert WKT string to geometry if provided
    if sweet_spot.sweet_spot_zone:
        db_sweet_spot.sweet_spot_zone = ST_GeomFromText(sweet_spot.sweet_spot_zone, 4326) # type: ignore

    db.add(db_sweet_spot)
    db.commit()
    db.refresh(db_sweet_spot)
    return db_sweet_spot

# ---- Get All Sweet Spots ----
@app.get("/sweet-spots/", response_model=List[SweetSpotResponse])
def get_sweet_spots(db: Session = Depends(database.get_db)):
    return db.query(db_models.SweetSpot).all()

# ---- Get Sweet Spots by Admin ID ----
@app.get("/sweet-spots/admin/{admin_id}", response_model=List[SweetSpotResponse])
def get_sweet_spots_by_admin(admin_id: int, db: Session = Depends(database.get_db)):
    return db.query(db_models.SweetSpot).filter(db_models.SweetSpot.admin_id == admin_id).all()


# ---- Create Administration ----
@app.post("/administrations/", response_model=AdministrationResponse)
def create_administration(admin:AdministrationCreate, db: Session = Depends(database.get_db)):
    db_admin = db_models.Administration(administration_name=admin.administration_name)
    db.add(db_admin)
    db.commit()
    db.refresh(db_admin)
    return db_admin

# ---- Create Zone ----
@app.post("/zones/", response_model=ZoneResponse)
def create_zone(zone: ZoneCreate, db: Session = Depends(database.get_db)):
    # Check if administration exists
    admin = db.query(db_models.Administration).filter_by(administration_id=zone.administration_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Administration not found")

    db_zone = db_models.AdministrationZone(administration_id=zone.administration_id)

    # Convert WKT strings to geometry
    if zone.boundary:
        db_zone.boundary = func.ST_GeomFromText(zone.boundary, 4326) # type: ignore
    if zone.danger_zone:
        db_zone.danger_zone = func.ST_GeomFromText(zone.danger_zone, 4326) # type: ignore
    if zone.path_zone:
        db_zone.path_zone = func.ST_GeomFromText(zone.path_zone, 4326) # type: ignore

    db.add(db_zone)
    db.commit()
    db.refresh(db_zone)
    return db_zone



@app.post("/check-point")
def check_point(location: Location, db: Session = Depends(database.get_db)):
    # Fetch administration
    admin = (
        db.query(db_models.Administration)
        .filter(
            db_models.Administration.administration_id == location.administration_id,
            db_models.Administration.administration_name == location.administration_name,
        )
        .first()
    )

    if not admin:
        raise HTTPException(status_code=404, detail="Administration not found")

    # Fetch the user (specific one from request)
    user = (
        db.query(db_models.User)
        .filter(
            db_models.User.user_id == location.user_id,
            db_models.User.administration_id == admin.administration_id
        )
        .first()
    )

    if not user:
        raise HTTPException(status_code=404, detail="User not found in this administration")

    # Fetch zones
    zone = (
        db.query(db_models.AdministrationZone)
        .filter(db_models.AdministrationZone.administration_id == admin.administration_id)
        .first()
    )

    if not zone:
        raise HTTPException(status_code=404, detail="Zones not defined for this administration")

    # Build point
    point = Point(location.lon, location.lat)
    alerts = []

    # Zone checks
    if zone.boundary is not None:
        boundary = load_wkt(db.scalar(func.ST_AsText(zone.boundary)))
        if not boundary.contains(point):
            alerts.append("Outside boundary")

    if zone.danger_zone is not None:
        danger = load_wkt(db.scalar(func.ST_AsText(zone.danger_zone)))
        if danger.contains(point):
            alerts.append("Inside danger zone")

    if zone.path_zone is not None:
        path = load_wkt(db.scalar(func.ST_AsText(zone.path_zone)))
        if not path.buffer(0.0001).contains(point):
            alerts.append("Outside path zone")

    # Final response for this single user
    return {
        "administration": {
            "id": admin.administration_id,
            "name": admin.administration_name,
        },
        "user": {
            "id": user.user_id,
            "username": user.username,
        },
        "coordinates": {"lat": location.lat, "lon": location.lon},
        "alerts": alerts if alerts else ["Safe"],
    }


@app.get("/nearest-police-stations/")
def get_nearest_police_stations(lat: float = Query(...), lon: float = Query(...)):
    url = f"https://api.geoapify.com/v2/places?categories=service.police&filter=circle:{lon},{lat},5000&limit=5&apiKey={API_KEY}"

    response = requests.get(url)
    if response.status_code != 200:
        return {"error": "Failed to fetch from Geoapify"}

    data = response.json()
    stations = []
    for feature in data.get("features", []):
        props = feature["properties"]
        stations.append({
            "name": props.get("name", "Unknown"),
            "address": props.get("formatted"),
            "lat": feature["geometry"]["coordinates"][1],
            "lon": feature["geometry"]["coordinates"][0],
            "distance_m": props.get("distance", "N/A")
        })

    return {"nearest_police_stations": stations}
