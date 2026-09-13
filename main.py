"""
WeatherGPT — simple all-in-one backend.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload

Environment:
    GEMINI_API_KEY=...
    GEMINI_MODEL=gemini-2.5-flash-lite
    JWT_SECRET=...
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

load_dotenv()

# ---------------- CONFIG ----------------

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "database.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-production")
JWT_ALGORITHM = "HS256"
TOKEN_MINUTES = 60 * 24

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

app = FastAPI(title="WeatherGPT API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# ---------------- DATABASE ----------------

DEFAULT_DB = {
    "users": [],
    "locations": [],
    "user_preferences": [],
    "chat_messages": [],
    "weather_records": [],
    "forecasts": [],
    "alerts": [],
    "advisories": [],
    "next_ids": {
        "users": 1,
        "locations": 1,
        "user_preferences": 1,
        "chat_messages": 1,
        "weather_records": 1,
        "forecasts": 1,
        "alerts": 1,
        "advisories": 1,
    },
}


def load_db():
    if not DB_FILE.exists():
        save_db(DEFAULT_DB)
    with DB_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_db(data):
    with DB_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def next_id(data, table):
    value = data["next_ids"][table]
    data["next_ids"][table] += 1
    return value


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------- MODELS ----------------

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    language: str = "en"


class LoginRequest(BaseModel):
    email: str
    password: str


class LocationRequest(BaseModel):
    name: str
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class ProfileUpdate(BaseModel):
    name: str | None = None
    language: str | None = None


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str


class PreferencesUpdate(BaseModel):
    timezone: str | None = None
    temperature_unit: str | None = None
    wind_speed_unit: str | None = None
    notifications_enabled: bool | None = None
    severe_alerts_enabled: bool | None = None


class ChatRequest(BaseModel):
    message: str
    language: str = "en"
    location: str | None = None
    conversation_id: str | None = None


# ---------------- AUTH ----------------

def create_token(user_id):
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    if not credentials:
        raise HTTPException(401, "Authentication required.")

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        user_id = int(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(401, "Invalid or expired token.")

    data = load_db()
    user = next((u for u in data["users"] if u["id"] == user_id), None)

    if not user or not user.get("is_active", True):
        raise HTTPException(401, "User not found or inactive.")

    return user


def public_user(user):
    result = dict(user)
    result.pop("password_hash", None)
    return result


# ---------------- WEATHER ----------------

WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Light rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


async def geocode(city):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            GEOCODING_URL,
            params={"name": city, "count": 1, "language": "en", "format": "json"},
        )
        response.raise_for_status()
        results = response.json().get("results") or []

    if not results:
        raise HTTPException(404, f"Location '{city}' was not found.")

    p = results[0]
    return {
        "city": p["name"],
        "country": p.get("country", ""),
        "latitude": p["latitude"],
        "longitude": p["longitude"],
        "timezone": p.get("timezone", "auto"),
    }


async def get_weather(city, days=7):
    place = await geocode(city)
    days = max(1, min(days, 16))

    params = {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "timezone": "auto",
        "forecast_days": days,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m,wind_direction_10m,"
            "surface_pressure"
        ),
        "hourly": (
            "temperature_2m,relative_humidity_2m,precipitation_probability,"
            "precipitation,weather_code,wind_speed_10m"
        ),
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,precipitation_sum,"
            "wind_speed_10m_max,sunrise,sunset"
        ),
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(WEATHER_URL, params=params)
        response.raise_for_status()
        raw = response.json()

    c = raw["current"]
    d = raw["daily"]

    current = {
        "temperature": c.get("temperature_2m"),
        "feels_like": c.get("apparent_temperature"),
        "humidity": c.get("relative_humidity_2m"),
        "wind_speed": c.get("wind_speed_10m"),
        "wind_direction": c.get("wind_direction_10m"),
        "precipitation": c.get("precipitation"),
        "pressure": c.get("surface_pressure"),
        "weather_code": c.get("weather_code"),
        "description": WEATHER_CODES.get(c.get("weather_code"), "Unknown"),
        "observed_at": c.get("time"),
    }

    forecast = []
    for i, date in enumerate(d["time"]):
        forecast.append({
            "date": date,
            "min_temperature": d["temperature_2m_min"][i],
            "max_temperature": d["temperature_2m_max"][i],
            "max_rain_probability": d["precipitation_probability_max"][i],
            "total_precipitation": d["precipitation_sum"][i],
            "wind_speed_max": d["wind_speed_10m_max"][i],
            "weather_code": d["weather_code"][i],
            "description": WEATHER_CODES.get(d["weather_code"][i], "Unknown"),
            "sunrise": d["sunrise"][i],
            "sunset": d["sunset"][i],
        })

    return {
        "location": place,
        "current": current,
        "forecast": forecast,
        "hourly": raw.get("hourly", {}),
    }


def build_alerts(weather):
    current = weather["current"]
    alerts = []

    temp = current.get("temperature")
    wind = current.get("wind_speed")
    code = current.get("weather_code")

    if temp is not None and temp >= 40:
        alerts.append({
            "alert_type": "extreme_heat",
            "severity": "high",
            "title": "Extreme heat",
            "message": f"Temperature is around {temp}°C. Stay hydrated and limit prolonged heat exposure.",
            "value": temp,
            "threshold": 40,
            "unit": "°C",
            "source": "WeatherGPT threshold alert",
            "detected_at": now_iso(),
        })

    if wind is not None and wind >= 50:
        alerts.append({
            "alert_type": "strong_wind",
            "severity": "high",
            "title": "Strong winds",
            "message": f"Wind speed is around {wind} km/h. Take care outdoors.",
            "value": wind,
            "threshold": 50,
            "unit": "km/h",
            "source": "WeatherGPT threshold alert",
            "detected_at": now_iso(),
        })

    if code in {95, 96, 99}:
        alerts.append({
            "alert_type": "thunderstorm",
            "severity": "high",
            "title": "Thunderstorm",
            "message": "Thunderstorm conditions are currently reported.",
            "value": code,
            "threshold": None,
            "unit": None,
            "source": "Open-Meteo weather code",
            "detected_at": now_iso(),
        })

    first = weather["forecast"][0] if weather["forecast"] else None
    if first and (first.get("max_rain_probability") or 0) >= 80:
        alerts.append({
            "alert_type": "heavy_rain_risk",
            "severity": "medium",
            "title": "High rain probability",
            "message": f"Rain probability today is about {first['max_rain_probability']}%.",
            "value": first["max_rain_probability"],
            "threshold": 80,
            "unit": "%",
            "source": "Open-Meteo forecast",
            "detected_at": now_iso(),
        })

    return alerts


# ---------------- GEMINI ----------------

async def ask_gemini(prompt, system_instruction=None):
    if not GEMINI_API_KEY:
        raise HTTPException(503, "GEMINI_API_KEY is not configured.")

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 700,
        },
    }

    if system_instruction:
        body["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            GEMINI_URL,
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json=body,
        )

    if response.status_code >= 400:
        try:
            error = response.json().get("error", {}).get("message")
        except Exception:
            error = None
        raise HTTPException(
            502,
            f"Gemini API error: {error or response.text[:300]}",
        )

    try:
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(502, "Gemini returned an unexpected response.")


# ---------------- SYSTEM ----------------

@app.get("/")
def root():
    return {"message": "WeatherGPT backend is running", "status": "online"}


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "gemini_configured": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL,
    }


# ---------------- AUTH ROUTES ----------------

@app.post("/api/auth/register")
def register(request: RegisterRequest):
    data = load_db()
    email = request.email.lower().strip()

    if any(u["email"] == email for u in data["users"]):
        raise HTTPException(409, "Email is already registered.")

    user = {
        "id": next_id(data, "users"),
        "name": request.name.strip(),
        "email": email,
        "password_hash": pwd_context.hash(request.password),
        "language": request.language,
        "is_active": True,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    data["users"].append(user)

    data["user_preferences"].append({
        "id": next_id(data, "user_preferences"),
        "user_id": user["id"],
        "timezone": "Asia/Kolkata",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "notifications_enabled": True,
        "severe_alerts_enabled": True,
    })

    save_db(data)
    return {
        "access_token": create_token(user["id"]),
        "token_type": "bearer",
        "user": public_user(user),
    }


@app.post("/api/auth/login")
def login(request: LoginRequest):
    data = load_db()
    user = next(
        (u for u in data["users"] if u["email"] == request.email.lower().strip()),
        None,
    )

    if not user or not pwd_context.verify(request.password, user["password_hash"]):
        raise HTTPException(401, "Incorrect email or password.")

    return {
        "access_token": create_token(user["id"]),
        "token_type": "bearer",
        "user": public_user(user),
    }


@app.get("/api/auth/me")
def auth_me(user=Depends(get_current_user)):
    return public_user(user)


# ---------------- WEATHER ROUTES ----------------

@app.get("/api/weather")
async def weather(city: str = Query(...)):
    return await get_weather(city, 7)


@app.get("/api/weather/current")
async def current_weather(city: str = Query(...)):
    data = await get_weather(city, 1)
    return {"location": data["location"], "weather": data["current"]}


@app.get("/api/weather/forecast")
async def forecast(
    city: str = Query(...),
    days: int = Query(7, ge=1, le=16),
):
    data = await get_weather(city, days)
    return {"location": data["location"], "forecast": data["forecast"]}


@app.get("/api/alerts")
async def alerts(city: str = Query(...)):
    data = await get_weather(city, 7)
    return {"location": data["location"], "alerts": build_alerts(data)}


# ---------------- CHAT ----------------

@app.post("/api/chat")
async def chat(request: ChatRequest, user=Depends(get_current_user)):
    city = request.location

    if not city:
        data = load_db()
        saved = next(
            (x for x in data["locations"] if x["user_id"] == user["id"]),
            None,
        )
        city = saved["name"] if saved else None

    if not city:
        raise HTTPException(400, "Please provide a location or save one first.")

    weather = await get_weather(city, 7)
    alerts = build_alerts(weather)

    context = {
        "location": weather["location"],
        "current": weather["current"],
        "forecast": weather["forecast"],
        "alerts": alerts,
    }

    system = (
        "You are WeatherGPT, a conversational weather assistant. "
        "Use ONLY the supplied weather data for weather facts. "
        "Do not invent temperatures, forecasts, alerts, or locations. "
        "Be concise, practical, and friendly. "
        f"Answer in the requested language: {request.language}."
    )

    prompt = (
        f"User question:\n{request.message}\n\n"
        f"Verified weather data:\n{json.dumps(context, ensure_ascii=False)}"
    )

    answer = await ask_gemini(prompt, system)

    data = load_db()
    message_id = next_id(data, "chat_messages")
    conversation_id = request.conversation_id or str(message_id)

    data["chat_messages"].append({
        "id": message_id,
        "user_id": user["id"],
        "conversation_id": conversation_id,
        "user_message": request.message,
        "assistant_message": answer,
        "location": city,
        "created_at": now_iso(),
    })
    save_db(data)

    return {
        "answer": answer,
        "location": weather["location"],
        "confidence": 0.9,
        "weather": weather["current"],
        "forecast": weather["forecast"],
        "alerts": alerts,
        "language": request.language,
        "generated_at": now_iso(),
    }


# ---------------- LOCATIONS ----------------

@app.get("/api/locations")
def get_locations(user=Depends(get_current_user)):
    data = load_db()
    return [x for x in data["locations"] if x["user_id"] == user["id"]]


@app.post("/api/locations")
def create_location(request: LocationRequest, user=Depends(get_current_user)):
    data = load_db()
    item = {
        "id": next_id(data, "locations"),
        "user_id": user["id"],
        "name": request.name,
        "country": request.country,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "created_at": now_iso(),
    }
    data["locations"].append(item)
    save_db(data)
    return item


@app.get("/api/locations/{location_id}")
def get_location(location_id: int, user=Depends(get_current_user)):
    data = load_db()
    item = next(
        (
            x for x in data["locations"]
            if x["id"] == location_id and x["user_id"] == user["id"]
        ),
        None,
    )
    if not item:
        raise HTTPException(404, "Location not found.")
    return item


@app.put("/api/locations/{location_id}")
def update_location(
    location_id: int,
    request: LocationRequest,
    user=Depends(get_current_user),
):
    data = load_db()
    item = next(
        (
            x for x in data["locations"]
            if x["id"] == location_id and x["user_id"] == user["id"]
        ),
        None,
    )
    if not item:
        raise HTTPException(404, "Location not found.")

    item.update({
        "name": request.name,
        "country": request.country,
        "latitude": request.latitude,
        "longitude": request.longitude,
    })
    save_db(data)
    return item


@app.delete("/api/locations/{location_id}")
def delete_location(location_id: int, user=Depends(get_current_user)):
    data = load_db()
    old_count = len(data["locations"])

    data["locations"] = [
        x for x in data["locations"]
        if not (x["id"] == location_id and x["user_id"] == user["id"])
    ]

    if len(data["locations"]) == old_count:
        raise HTTPException(404, "Location not found.")

    save_db(data)
    return {"message": "Location deleted."}


# ---------------- PROFILE ----------------

@app.get("/api/users/me")
def get_profile(user=Depends(get_current_user)):
    return public_user(user)


@app.put("/api/users/me")
def update_profile(request: ProfileUpdate, user=Depends(get_current_user)):
    data = load_db()
    db_user = next(u for u in data["users"] if u["id"] == user["id"])

    if request.name is not None:
        db_user["name"] = request.name.strip()
    if request.language is not None:
        db_user["language"] = request.language.strip()

    db_user["updated_at"] = now_iso()
    save_db(data)
    return public_user(db_user)


@app.put("/api/users/me/password")
def change_password(
    request: PasswordUpdate,
    user=Depends(get_current_user),
):
    if not pwd_context.verify(request.current_password, user["password_hash"]):
        raise HTTPException(400, "Current password is incorrect.")

    data = load_db()
    db_user = next(u for u in data["users"] if u["id"] == user["id"])
    db_user["password_hash"] = pwd_context.hash(request.new_password)
    db_user["updated_at"] = now_iso()
    save_db(data)

    return {"message": "Password changed successfully."}


# ---------------- PREFERENCES ----------------

@app.get("/api/users/me/preferences")
def get_preferences(user=Depends(get_current_user)):
    data = load_db()
    pref = next(
        (x for x in data["user_preferences"] if x["user_id"] == user["id"]),
        None,
    )

    if not pref:
        pref = {
            "id": next_id(data, "user_preferences"),
            "user_id": user["id"],
            "timezone": "Asia/Kolkata",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "notifications_enabled": True,
            "severe_alerts_enabled": True,
        }
        data["user_preferences"].append(pref)
        save_db(data)

    return pref


@app.put("/api/users/me/preferences")
def update_preferences(
    request: PreferencesUpdate,
    user=Depends(get_current_user),
):
    data = load_db()
    pref = next(
        (x for x in data["user_preferences"] if x["user_id"] == user["id"]),
        None,
    )

    if not pref:
        pref = {
            "id": next_id(data, "user_preferences"),
            "user_id": user["id"],
        }
        data["user_preferences"].append(pref)

    pref.update(request.model_dump(exclude_none=True))
    save_db(data)
    return pref
