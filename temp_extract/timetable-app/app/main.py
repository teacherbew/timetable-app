import csv
import io
import json
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app import crud_helpers, models
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
    ClassGroupCreate,
    ClassGroupResponse,
    RoomCreate,
    RoomResponse,
    ScheduleDataContent,
    ScheduleResponseWrapper,
    SubjectCreate,
    SubjectResponse,
    TeacherCreate,
    TeacherResponse,
    TimetableSlotCreate,
    TimetableSlotResponse,
)

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="School Timetable API")

# CORS: allows the web frontend (hosted on a different domain) to call this
# API from the browser. Writes are still protected by JWT auth, so a
# permissive origin list here is fine — it only affects which *websites* the
# browser will let call this API, not who can authenticate.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
# MASTER DATA: teachers / subjects / rooms / class groups
# Each has the same shape: list, create, update, delete, bulk CSV upload.
# ----------------------------------------------------

def _register_master_data_routes(path: str, tag: str, model, create_schema, response_schema, label: str):
    @app.get(f"/{path}", tags=[tag], response_model=list[response_schema])
    def list_items(db: Session = Depends(get_db)):
        return crud_helpers.list_all(db, model)

    @app.post(f"/{path}", tags=[tag], response_model=response_schema)
    def create_item(
        item: create_schema,
        db: Session = Depends(get_db),
        current_user: models.User = Depends(require_roles(["admin", "teacher"])),
    ):
        return crud_helpers.create_one(db, model, item.model_dump())

    @app.put(f"/{path}/{{item_id}}", tags=[tag], response_model=response_schema)
    def update_item(
        item_id: int,
        item: create_schema,
        db: Session = Depends(get_db),
        current_user: models.User = Depends(require_roles(["admin", "teacher"])),
    ):
        return crud_helpers.update_one(db, model, item_id, item.model_dump(), label)

    @app.delete(f"/{path}/{{item_id}}", tags=[tag])
    def delete_item(
        item_id: int,
        db: Session = Depends(get_db),
        current_user: models.User = Depends(require_roles(["admin"])),
    ):
        return crud_helpers.delete_one(db, model, item_id, label)

    @app.post(f"/{path}/upload-csv", tags=[tag], dependencies=[Depends(rate_limit)])
    def upload_items_csv(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user: models.User = Depends(require_roles(["admin", "teacher"])),
    ):
        return crud_helpers.bulk_upload_csv(db, model, create_schema, file, label)


_register_master_data_routes("teachers", "Teachers", models.Teacher, TeacherCreate, TeacherResponse, "ครู")
_register_master_data_routes("subjects", "Subjects", models.Subject, SubjectCreate, SubjectResponse, "วิชา")
_register_master_data_routes("rooms", "Rooms", models.Room, RoomCreate, RoomResponse, "ห้องเรียน")
_register_master_data_routes("class-groups", "ClassGroups", models.ClassGroup, ClassGroupCreate, ClassGroupResponse, "ระดับชั้น")


# ----------------------------------------------------
# SHARED QUERY HELPER
# ----------------------------------------------------
def _filtered_slots_query(
    db: Session,
    day: Optional[str],
    teacher_id: Optional[int],
    room_id: Optional[int],
    class_group_id: Optional[int],
):
    query = db.query(models.TimetableSlot).options(
        joinedload(models.TimetableSlot.teacher),
        joinedload(models.TimetableSlot.subject),
        joinedload(models.TimetableSlot.room),
        joinedload(models.TimetableSlot.class_group),
    )
    if day:
        query = query.filter(models.TimetableSlot.day.ilike(day))
    if teacher_id:
        query = query.filter(models.TimetableSlot.teacher_id == teacher_id)
    if room_id:
        query = query.filter(models.TimetableSlot.room_id == room_id)
    if class_group_id:
        query = query.filter(models.TimetableSlot.class_group_id == class_group_id)
    return query


def _clean_filters(
    day: Optional[str],
    teacher_id: Optional[int],
    room_id: Optional[int],
    class_group_id: Optional[int] = None,
):
    clean_day = day.strip() if day and day.strip() and day.strip().lower() != "string" else None
    clean_teacher = teacher_id if teacher_id is not None and teacher_id > 0 else None
    clean_room = room_id if room_id is not None and room_id > 0 else None
    clean_class_group = class_group_id if class_group_id is not None and class_group_id > 0 else None
    return clean_day, clean_teacher, clean_room, clean_class_group


def _check_conflicts(db: Session, day: str, period: int, teacher_id: int, room_id: int, class_group_id: int):
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

    class_busy = db.query(models.TimetableSlot).filter(
        models.TimetableSlot.day == day,
        models.TimetableSlot.period == period,
        models.TimetableSlot.class_group_id == class_group_id,
    ).first()
    if class_busy:
        raise HTTPException(
            status_code=400,
            detail=f"ระดับชั้น ID {class_group_id} มีเรียนวิชาอื่นในวัน {day} คาบที่ {period} อยู่แล้ว",
        )


# ----------------------------------------------------
# TIMETABLE MANAGEMENT
# ----------------------------------------------------

@app.get("/api/v1/schedules", response_model=ScheduleResponseWrapper, tags=["Timetable"])
def get_schedules(
    day: Optional[str] = Query(None, description="วัน เช่น Monday, Tuesday"),
    teacher_id: Optional[int] = Query(None, description="ID ครู"),
    room_id: Optional[int] = Query(None, description="ID ห้อง"),
    class_group_id: Optional[int] = Query(None, description="ID ระดับชั้น"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Always hits the database directly (no cache) — useful when you need
    guaranteed-fresh data. For a cached, filtered read, use GET /timetable/."""
    clean_day, clean_teacher, clean_room, clean_class_group = _clean_filters(day, teacher_id, room_id, class_group_id)
    query = _filtered_slots_query(db, clean_day, clean_teacher, clean_room, clean_class_group)

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
    class_group_id: Optional[int] = Query(None, description="ID ระดับชั้น"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Same data as /api/v1/schedules, but cached in Redis for 60s per unique
    filter/page combination. Use this for read-heavy traffic (e.g. a frontend
    that polls often)."""
    clean_day, clean_teacher, clean_room, clean_class_group = _clean_filters(day, teacher_id, room_id, class_group_id)
    cache_key = f"timetable:day={clean_day}:teacher={clean_teacher}:room={clean_room}:class={clean_class_group}:page={page}:limit={limit}"

    try:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            return {"source": "cache", "data": json.loads(cached_data)}
    except Exception as e:
        print(f"Redis Cache Error: {e}")

    query = _filtered_slots_query(db, clean_day, clean_teacher, clean_room, clean_class_group)
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
                "class_group": {"id": s.class_group.id, "name": s.class_group.name, "level": s.class_group.level} if s.class_group else None,
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
    _check_conflicts(
        db, slot_data.day, slot_data.period, slot_data.teacher_id, slot_data.room_id, slot_data.class_group_id
    )

    try:
        new_slot = models.TimetableSlot(**slot_data.model_dump())
        db.add(new_slot)
        db.commit()
        db.refresh(new_slot)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="ไม่สามารถสร้างได้: ตรวจสอบ teacher_id, subject_id, room_id, class_group_id ว่ามีในระบบหรือไม่",
        )

    try:
        redis_client.flushdb()
    except Exception:
        pass

    return {
        "message": f"สร้างคาบเรียนสำเร็จโดย {current_user.username}",
        "data": TimetableSlotResponse.model_validate(new_slot),
    }


@app.delete("/timetable/{slot_id}", tags=["Timetable"])
def delete_timetable_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin", "teacher"])),
):
    slot = db.query(models.TimetableSlot).filter(models.TimetableSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail=f"ไม่พบคาบเรียน ID {slot_id}")
    db.delete(slot)
    db.commit()
    try:
        redis_client.flushdb()
    except Exception:
        pass
    return {"message": f"ลบคาบเรียน ID {slot_id} สำเร็จ"}


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
    db_class_slots = set(
        (s.day, s.period, s.class_group_id)
        for s in db.query(models.TimetableSlot.day, models.TimetableSlot.period, models.TimetableSlot.class_group_id).all()
        if s.class_group_id is not None
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
                class_group_id=int(row["class_group_id"]),
            )
        except (KeyError, ValueError, ValidationError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"ข้อมูลบรรทัดที่ {line_num} ไม่ถูกต้อง: {e}",
            )

        teacher_key = (slot_data.day, slot_data.period, slot_data.teacher_id)
        room_key = (slot_data.day, slot_data.period, slot_data.room_id)
        class_key = (slot_data.day, slot_data.period, slot_data.class_group_id)

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
        if class_key in db_class_slots:
            raise HTTPException(
                status_code=400,
                detail=f"ข้อมูลบรรทัดที่ {line_num} ขัดแย้ง: ระดับชั้น ID {slot_data.class_group_id} มีเรียนวิชาอื่นในวัน {slot_data.day} คาบที่ {slot_data.period} อยู่แล้ว",
            )

        db_teacher_slots.add(teacher_key)
        db_room_slots.add(room_key)
        db_class_slots.add(class_key)
        new_slots.append(models.TimetableSlot(**slot_data.model_dump()))

    try:
        db.add_all(new_slots)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="นำเข้าไม่สำเร็จ: มี teacher_id, subject_id, room_id หรือ class_group_id ใน CSV ที่ไม่มีอยู่ในระบบ",
        )

    try:
        redis_client.flushdb()
    except Exception:
        pass

    return {
        "message": f"นำเข้าข้อมูลสำเร็จ {len(new_slots)} รายการ",
        "imported_by": current_user.username,
    }
