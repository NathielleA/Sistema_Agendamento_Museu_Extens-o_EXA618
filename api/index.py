import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from bson import ObjectId
from fastapi import Body, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from pymongo import ASCENDING, MongoClient
from pymongo.errors import ServerSelectionTimeoutError

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

MONGODB_URI = os.environ.get("MONGODB_URI") or "mongodb://localhost:27017"
MONGODB_DB = os.environ.get("MONGODB_DB") or "museu_agendamentos"
SERVER_TIMEZONE = timezone(timedelta(hours=int(os.environ.get("TZ_OFFSET_HOURS") or "-3")))

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"

mongo_client: Optional[MongoClient] = None
db = None


DEFAULT_SETTINGS: Dict[str, Any] = {
    "open_weekdays": [0, 1, 2, 3, 4],
    "open_time": "09:00",
    "close_time": "17:00",
    "slot_minutes": 60,
    "capacity_per_slot": 40,
    "lead_time_days": 1,
    "max_days_ahead": 90,
}


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SERVER_TIMEZONE)
    return dt.astimezone(timezone.utc)


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(hour=int(hh), minute=int(mm), tzinfo=SERVER_TIMEZONE)


def _jsonify_mongo(doc: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.astimezone(timezone.utc).isoformat()
        else:
            out[k] = v
    if "_id" in out:
        out["id"] = out.pop("_id")
    return out


def _require_db():
    global mongo_client, db
    if mongo_client is None or db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco indisponível. Configure MONGODB_URI (ex.: mongodb://localhost:27017 ou MongoDB Atlas).",
        )
    try:
        mongo_client.admin.command("ping")
    except ServerSelectionTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível conectar ao MongoDB. Verifique MONGODB_URI e se o servidor está acessível.",
        )
    return db


def _get_settings() -> Dict[str, Any]:
    database = _require_db()
    doc = database.settings.find_one({"_id": "default"})
    if not doc:
        database.settings.update_one(
            {"_id": "default"},
            {"$set": DEFAULT_SETTINGS | {"updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return DEFAULT_SETTINGS
    doc.pop("_id", None)
    doc.pop("updated_at", None)
    merged = DEFAULT_SETTINGS | doc
    return merged


def _slot_bounds(start_local: datetime, settings: Dict[str, Any]) -> tuple[datetime, datetime]:
    minutes = int(settings["slot_minutes"])
    end_local = start_local + timedelta(minutes=minutes)
    return start_local, end_local


def _validate_slot(start_local: datetime, group_size: int, settings: Dict[str, Any]) -> None:
    now_local = datetime.now(SERVER_TIMEZONE)
    if start_local.tzinfo is None:
        start_local = start_local.replace(tzinfo=SERVER_TIMEZONE)

    if start_local < now_local + timedelta(days=int(settings["lead_time_days"])):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Data/hora muito próxima. Escolha uma visita com antecedência.",
        )
    if start_local.date() > (now_local.date() + timedelta(days=int(settings["max_days_ahead"]))):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Data muito distante. Escolha uma visita em um prazo menor.",
        )

    if start_local.weekday() not in set(settings["open_weekdays"]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O museu não atende nesse dia da semana.",
        )

    open_t = _parse_hhmm(settings["open_time"])
    close_t = _parse_hhmm(settings["close_time"])
    start_t = start_local.timetz()
    if not (open_t <= start_t < close_t):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Horário fora do funcionamento do museu.",
        )

    capacity = int(settings["capacity_per_slot"])
    if group_size <= 0 or group_size > capacity:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tamanho do grupo inválido. Máximo por horário: {capacity}.",
        )


class VisitorModel(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=30)


class GroupModel(BaseModel):
    size: int = Field(gt=0, le=500)
    institution: Optional[str] = Field(default=None, max_length=150)
    city: Optional[str] = Field(default=None, max_length=80)
    state: Optional[str] = Field(default=None, max_length=2, description="UF")


class AppointmentCreate(BaseModel):
    start: datetime = Field(description="Data/hora local. Ex.: 2026-06-10T10:00:00-03:00")
    visitor: VisitorModel
    group: GroupModel
    purpose: str = Field(min_length=2, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=1000)
    accessibility_needs: Optional[str] = Field(default=None, max_length=300)


class AppointmentStatusUpdate(BaseModel):
    status: Literal["pending", "confirmed", "cancelled"]


class FeedbackCreate(BaseModel):
    appointment_id: str
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=2000)
    suggestions: Optional[str] = Field(default=None, max_length=2000)


@app.on_event("startup")
def _startup():
    global mongo_client, db
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=2000)
    try:
        mongo_client.admin.command("ping")
        db = mongo_client[MONGODB_DB]
        db.appointments.create_index([("start", ASCENDING)])
        db.appointments.create_index([("status", ASCENDING), ("start", ASCENDING)])
        db.appointments.create_index([("visitor.email", ASCENDING), ("start", ASCENDING)])
        db.feedback.create_index([("created_at", ASCENDING)])
        db.content.create_index([("_id", ASCENDING)], unique=True)
        db.settings.create_index([("_id", ASCENDING)], unique=True)
        _get_settings()
    except ServerSelectionTimeoutError:
        db = None


@app.on_event("shutdown")
def _shutdown():
    global mongo_client
    if mongo_client is not None:
        mongo_client.close()


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def root():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"service": "agendamento-museu", "status": "ok"}


@app.get("/health")
def health():
    try:
        _require_db()
        return {"ok": True, "db": "mongo", "database": MONGODB_DB}
    except HTTPException as e:
        return {"ok": False, "db": "mongo", "error": e.detail}


@app.get("/content")
def get_content():
    database = _require_db()
    rules = database.content.find_one({"_id": "rules"})
    institutional = database.content.find_one({"_id": "institutional"})
    return {
        "rules": (rules or {}).get("text")
        or "Regras de visitação ainda não cadastradas.",
        "institutional_info": (institutional or {}).get("text")
        or "Informações institucionais ainda não cadastradas.",
        "settings": _get_settings(),
    }


@app.put("/content")
def put_content(
    rules: Optional[str] = Body(default=None),
    institutional_info: Optional[str] = Body(default=None),
):
    database = _require_db()
    now = datetime.now(timezone.utc)
    if rules is not None:
        database.content.update_one(
            {"_id": "rules"},
            {"$set": {"text": rules, "updated_at": now}},
            upsert=True,
        )
    if institutional_info is not None:
        database.content.update_one(
            {"_id": "institutional"},
            {"$set": {"text": institutional_info, "updated_at": now}},
            upsert=True,
        )
    return {"ok": True}


@app.get("/availability")
def availability(day: date = Query(..., description="Data no formato YYYY-MM-DD")):
    database = _require_db()
    settings = _get_settings()
    open_t = _parse_hhmm(settings["open_time"])
    close_t = _parse_hhmm(settings["close_time"])
    slot_minutes = int(settings["slot_minutes"])
    capacity = int(settings["capacity_per_slot"])

    start_dt = datetime.combine(day, time(open_t.hour, open_t.minute, tzinfo=SERVER_TIMEZONE))
    end_dt = datetime.combine(day, time(close_t.hour, close_t.minute, tzinfo=SERVER_TIMEZONE))

    slots: List[Dict[str, Any]] = []
    cur = start_dt
    while cur + timedelta(minutes=slot_minutes) <= end_dt:
        slot_start_local = cur
        slot_end_local = cur + timedelta(minutes=slot_minutes)
        start_utc = _utc(slot_start_local)
        end_utc = _utc(slot_end_local)

        pipeline = [
            {
                "$match": {
                    "start": {"$gte": start_utc, "$lt": end_utc},
                    "status": {"$in": ["pending", "confirmed"]},
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$group.size"}}},
        ]
        agg = list(database.appointments.aggregate(pipeline))
        booked = int(agg[0]["total"]) if agg else 0
        remaining = max(0, capacity - booked)
        slots.append(
            {
                "start": slot_start_local.isoformat(),
                "end": slot_end_local.isoformat(),
                "capacity": capacity,
                "booked": booked,
                "remaining": remaining,
            }
        )
        cur = slot_end_local

    return {
        "day": day.isoformat(),
        "weekday": day.weekday(),
        "open": day.weekday() in set(settings["open_weekdays"]),
        "slots": slots,
    }


@app.post("/appointments", status_code=status.HTTP_201_CREATED)
def create_appointment(payload: AppointmentCreate):
    database = _require_db()
    settings = _get_settings()

    start_local = payload.start
    if start_local.tzinfo is None:
        start_local = start_local.replace(tzinfo=SERVER_TIMEZONE)
    _validate_slot(start_local, payload.group.size, settings)

    start_local, end_local = _slot_bounds(start_local, settings)
    start_utc = _utc(start_local)
    end_utc = _utc(end_local)

    capacity = int(settings["capacity_per_slot"])
    pipeline = [
        {
            "$match": {
                "start": {"$gte": start_utc, "$lt": end_utc},
                "status": {"$in": ["pending", "confirmed"]},
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$group.size"}}},
    ]
    agg = list(database.appointments.aggregate(pipeline))
    booked = int(agg[0]["total"]) if agg else 0
    if booked + payload.group.size > capacity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não há vagas suficientes nesse horário. Escolha outro horário.",
        )

    doc = {
        "created_at": datetime.now(timezone.utc),
        "status": "pending",
        "start": start_utc,
        "end": end_utc,
        "start_local": start_local.isoformat(),
        "end_local": end_local.isoformat(),
        "visitor": payload.visitor.dict(),
        "group": payload.group.dict(),
        "purpose": payload.purpose,
        "notes": payload.notes,
        "accessibility_needs": payload.accessibility_needs,
        "origin": "web",
    }
    res = database.appointments.insert_one(doc)
    saved = database.appointments.find_one({"_id": res.inserted_id})
    return _jsonify_mongo(saved)


@app.get("/appointments")
def list_appointments(
    status_filter: Optional[Literal["pending", "confirmed", "cancelled"]] = Query(default=None),
    start_from: Optional[datetime] = Query(default=None, description="ISO datetime"),
    start_to: Optional[datetime] = Query(default=None, description="ISO datetime"),
    email: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    database = _require_db()
    q: Dict[str, Any] = {}
    if status_filter:
        q["status"] = status_filter
    if email:
        q["visitor.email"] = email
    if start_from or start_to:
        q["start"] = {}
        if start_from:
            q["start"]["$gte"] = _utc(start_from)
        if start_to:
            q["start"]["$lte"] = _utc(start_to)

    docs = list(database.appointments.find(q).sort("start", ASCENDING).limit(limit))
    return {"items": [_jsonify_mongo(d) for d in docs]}


@app.get("/appointments/{appointment_id}")
def get_appointment(appointment_id: str):
    database = _require_db()
    try:
        oid = ObjectId(appointment_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agendamento não encontrado")
    doc = database.appointments.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agendamento não encontrado")
    return _jsonify_mongo(doc)


@app.patch("/appointments/{appointment_id}/status")
def update_status(appointment_id: str, payload: AppointmentStatusUpdate):
    database = _require_db()
    try:
        oid = ObjectId(appointment_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agendamento não encontrado")
    res = database.appointments.update_one(
        {"_id": oid},
        {"$set": {"status": payload.status, "updated_at": datetime.now(timezone.utc)}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agendamento não encontrado")
    doc = database.appointments.find_one({"_id": oid})
    return _jsonify_mongo(doc)


@app.post("/feedback", status_code=status.HTTP_201_CREATED)
def create_feedback(payload: FeedbackCreate):
    database = _require_db()
    try:
        appointment_oid = ObjectId(payload.appointment_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="appointment_id inválido")

    appt = database.appointments.find_one({"_id": appointment_oid})
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agendamento não encontrado")

    doc = {
        "created_at": datetime.now(timezone.utc),
        "appointment_id": appointment_oid,
        "rating": payload.rating,
        "comment": payload.comment,
        "suggestions": payload.suggestions,
    }
    res = database.feedback.insert_one(doc)
    saved = database.feedback.find_one({"_id": res.inserted_id})
    out = _jsonify_mongo(saved)
    out["appointment_id"] = str(saved["appointment_id"])
    return out


@app.get("/feedback")
def list_feedback(limit: int = Query(default=50, ge=1, le=200)):
    database = _require_db()
    docs = list(database.feedback.find({}).sort("created_at", -1).limit(limit))
    items = []
    for d in docs:
        out = _jsonify_mongo(d)
        if "appointment_id" in d:
            out["appointment_id"] = str(d["appointment_id"])
        items.append(out)
    return {"items": items}

