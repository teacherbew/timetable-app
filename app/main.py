import csv
import io
import json
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app import models
from app.auth import (
    create_access_token,
    get_password_hash,
    get_current_user,
    require_roles,
    verify_password,
)
from app.database import engine, get_db
from app.rate_limiter import rate_limit
from app.redis_client import redis_client
from app.schemas import (
    ScheduleDataContent,
    ScheduleResponseWrapper,
    TimetableSlotCreate,
    TimetableSlotResponse,
)

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="School Timetable API")


@app.get("/")
def read_root():
    return {"message": "Welcome to School Timetable API"}


# ----------------------------------------------------
# AUTHENTICATION
# ----------------------------------------------------
@app.post("/login", tags=["Auth"], dependencies=[Depends(rate_limit)])
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer"}


# ----------------------------------------------------
# SHARED QUERY HELPER
# ----------------------------------------------------
def _filtered_slots_query(
    db: Session,
    day: Optional[str],
    teacher_id: Optional[int],
    room_id: Optional[int],
):
    query = db.query(models.TimetableSlot).options(
        joinedload(models.TimetableSlot.teacher),
        joinedload(models.TimetableSlot.subject),
        joinedload(models.TimetableSlot.room),
    )
    if day:
        query = query.filter(models.TimetableSlot.day.ilike(day))
    if teacher_id:
        query = query.filter(models.TimetableSlot.teacher_id == teacher_id)
    if room_id:
        query = query.filter(models.TimetableSlot.room_id == room_id)
    return query


def _clean_filters(day: Optional[str], teacher_id: Optional[int], room_id: Optional[int]):
    clean_day = day.strip() if day and day.strip() and day.strip().lower() != "string" else None
    clean_teacher = teacher_id if teacher_id is not None and teacher_id > 0 else None
    clean_room = room_id if room_id is not None and room_id > 0 else None
    return clean_day, clean_teacher, clean_room


def _check_conflicts(db: Session, day: str, period: int, teacher_id: int, room_id: int):
    teacher_busy = db.query(models.TimetableSlot).filter(
        models.TimetableSlot.day == day,
        models.TimetableSlot.period == period,
        models.TimetableSlot.teacher_id == teacher_id,
    ).first()
    if teacher_busy:
        raise HTTPException(
            status_code=400,
            detail=f"ครู ID {teacher_id} มีสอนในวัน {day} คาบที่ {period} อยู่แล้ว",
        )

    room_busy = db.query(models.TimetableSlot).filter(
        models.TimetableSlot.day == day,
        models.TimetableSlot.period == period,
        models.TimetableSlot.room_id == room_id,
    ).first()
    if room_busy:
        raise HTTPException(
            status_code=400,
            detail=f"ห้องเรียน ID {room_id} ถูกใช้งานในวัน {day} คาบที่ {period} อยู่แล้ว",
        )


# ----------------------------------------------------
# TIMETABLE MANAGEMENT
# ----------------------------------------------------

@app.get("/api/v1/schedules", response_model=ScheduleResponseWrapper, tags=["Timetable"])
def get_schedules(
    day: Optional[str] = Query(None, description="วัน เช่น Monday, Tuesday"),
    teacher_id: Optional[int] = Query(None, description="ID ครู"),
    room_id: Optional[int] = Query(None, description="ID ห้อง"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Always hits the database directly (no cache) — useful when you need
    guaranteed-fresh data. For a cached, filtered read, use GET /timetable/."""
    clean_day, clean_teacher, clean_room = _clean_filters(day, teacher_id, room_id)
    query = _filtered_slots_query(db, clean_day, clean_teacher, clean_room)

    total_items = query.count()
    offset = (page - 1) * limit
    slots = query.offset(offset).limit(limit).all()

    return {
        "source": "database",
        "data": ScheduleDataContent(
            total_items=total_items,
            page=page,
            limit=limit,
            total_pages=(total_items + limit - 1) // limit if total_items > 0 else 1,
            items=[TimetableSlotResponse.model_validate(s) for s in slots],
        ),
    }


@app.get("/timetable/", tags=["Timetable"])
def get_timetable(
    day: Optional[str] = Query(None, description="วัน เช่น Monday, Tuesday"),
    teacher_id: Optional[int] = Query(None, description="ID ครู"),
    room_id: Optional[int] = Query(None, description="ID ห้อง"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Same data as /api/v1/schedules, but cached in Redis for 60s per unique
    filter/page combination. Use this for read-heavy traffic (e.g. a frontend
    that polls often)."""
    clean_day, clean_teacher, clean_room = _clean_filters(day, teacher_id, room_id)
    cache_key = f"timetable:day={clean_day}:teacher={clean_teacher}:room={clean_room}:page={page}:limit={limit}"

    try:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            return {"source": "cache", "data": json.loads(cached_data)}
    except Exception as e:
        print(f"Redis Cache Error: {e}")

    query = _filtered_slots_query(db, clean_day, clean_teacher, clean_room)
    total_items = query.count()
    offset = (page - 1) * limit
    slots = query.offset(offset).limit(limit).all()

    result = {
        "total_items": total_items,
        "page": page,
        "limit": limit,
        "total_pages": (total_items + limit - 1) // limit if total_items > 0 else 1,
        "items": [
            {
                "id": s.id,
                "day": s.day,
                "period": s.period,
                "teacher": {"id": s.teacher.id, "name": s.teacher.name, "email": s.teacher.email} if s.teacher else None,
                "subject": {"id": s.subject.id, "code": s.subject.code, "name": s.subject.name} if s.subject else None,
                "room": {"id": s.room.id, "name": s.room.name, "capacity": s.room.capacity} if s.room else None,
            }
            for s in slots
        ],
    }

    try:
        redis_client.set(cache_key, json.dumps(result), ex=60)
    except Exception as e:
        print(f"Redis Set Error: {e}")

    return {"source": "database", "data": result}


@app.post("/timetable/", tags=["Timetable"])
def create_timetable_slot(
    slot_data: TimetableSlotCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin", "teacher"])),
):
    _check_conflicts(db, slot_data.day, slot_data.period, slot_data.teacher_id, slot_data.room_id)

    try:
        new_slot = models.TimetableSlot(**slot_data.model_dump())
        db.add(new_slot)
        db.commit()
        db.refresh(new_slot)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="ไม่สามารถสร้างได้: ตรวจสอบ teacher_id, subject_id, room_id ว่ามีในระบบหรือไม่",
        )

    try:
        redis_client.flushdb()
    except Exception:
        pass

    return {
        "message": f"สร้างคาบเรียนสำเร็จโดย {current_user.username}",
        "data": TimetableSlotResponse.model_validate(new_slot),
    }


@app.post("/timetable/upload-csv", tags=["Timetable"], dependencies=[Depends(rate_limit)])
def upload_timetable_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin", "teacher"])),
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="กรุณาอัปโหลดไฟล์ .csv เท่านั้น")

    contents = file.file.read().decode("utf-8-sig")
    buffer = io.StringIO(contents)
    reader = csv.DictReader(buffer)

    db_teacher_slots = set(
        (s.day, s.period, s.teacher_id)
        for s in db.query(models.TimetableSlot.day, models.TimetableSlot.period, models.TimetableSlot.teacher_id).all()
    )
    db_room_slots = set(
        (s.day, s.period, s.room_id)
        for s in db.query(models.TimetableSlot.day, models.TimetableSlot.period, models.TimetableSlot.room_id).all()
    )

    new_slots = []
    line_num = 1
    for row in reader:
        line_num += 1
        try:
            slot_data = TimetableSlotCreate(
                day=row["day"],
                period=int(row["period"]),
                teacher_id=int(row["teacher_id"]),
                subject_id=int(row["subject_id"]),
                room_id=int(row["room_id"]),
            )
        except (KeyError, ValueError, ValidationError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"ข้อมูลบรรทัดที่ {line_num} ไม่ถูกต้อง: {e}",
            )

        teacher_key = (slot_data.day, slot_data.period, slot_data.teacher_id)
        room_key = (slot_data.day, slot_data.period, slot_data.room_id)

        if teacher_key in db_teacher_slots:
            raise HTTPException(
                status_code=400,
                detail=f"ข้อมูลบรรทัดที่ {line_num} ขัดแย้ง: ครู ID {slot_data.teacher_id} มีสอนในวัน {slot_data.day} คาบที่ {slot_data.period} อยู่แล้ว",
            )
        if room_key in db_room_slots:
            raise HTTPException(
                status_code=400,
                detail=f"ข้อมูลบรรทัดที่ {line_num} ขัดแย้ง: ห้อง ID {slot_data.room_id} ถูกใช้งานในวัน {slot_data.day} คาบที่ {slot_data.period} อยู่แล้ว",
            )

        db_teacher_slots.add(teacher_key)
        db_room_slots.add(room_key)
        new_slots.append(models.TimetableSlot(**slot_data.model_dump()))

    try:
        db.add_all(new_slots)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="นำเข้าไม่สำเร็จ: มี teacher_id, subject_id หรือ room_id ใน CSV ที่ไม่มีอยู่ในระบบ",
        )

    try:
        redis_client.flushdb()
    except Exception:
        pass

    return {
        "message": f"นำเข้าข้อมูลสำเร็จ {len(new_slots)} รายการ",
        "imported_by": current_user.username,
    }
