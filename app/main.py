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
    AssignmentCreate,
    AssignmentResponse,
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
# ASSIGNMENTS (ภาระงานสอน) — the pool of "cards" the drag-and-drop UI draws from
# ----------------------------------------------------

@app.get("/assignments", tags=["Assignments"], response_model=list[AssignmentResponse])
def list_assignments(
    class_group_id: Optional[int] = Query(None),
    teacher_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(models.Assignment).options(
        joinedload(models.Assignment.teacher),
        joinedload(models.Assignment.subject),
        joinedload(models.Assignment.class_group),
    )
    if class_group_id:
        query = query.filter(models.Assignment.class_group_id == class_group_id)
    if teacher_id:
        query = query.filter(models.Assignment.teacher_id == teacher_id)
    assignments = query.order_by(models.Assignment.id).all()

    # One query for ALL scheduled-counts instead of one query per assignment
    # (that N+1 pattern was the real cause of the ~10s load time with 900+ rows).
    from sqlalchemy import func
    count_rows = db.query(
        models.TimetableSlot.teacher_id,
        models.TimetableSlot.subject_id,
        models.TimetableSlot.class_group_id,
        func.count(models.TimetableSlot.id),
    ).group_by(
        models.TimetableSlot.teacher_id,
        models.TimetableSlot.subject_id,
        models.TimetableSlot.class_group_id,
    ).all()
    count_map = {(t, s, c): n for t, s, c, n in count_rows}

    results = []
    for a in assignments:
        resp = AssignmentResponse.model_validate(a)
        resp.scheduled_count = count_map.get((a.teacher_id, a.subject_id, a.class_group_id), 0)
        results.append(resp)
    return results


@app.post("/assignments", tags=["Assignments"], response_model=AssignmentResponse)
def create_assignment(
    item: AssignmentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin", "teacher"])),
):
    obj = crud_helpers.create_one(db, models.Assignment, item.model_dump())
    resp = AssignmentResponse.model_validate(obj)
    resp.scheduled_count = 0
    return resp


@app.put("/assignments/{item_id}", tags=["Assignments"], response_model=AssignmentResponse)
def update_assignment(
    item_id: int,
    item: AssignmentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin", "teacher"])),
):
    obj = crud_helpers.update_one(db, models.Assignment, item_id, item.model_dump(), "ภาระงานสอน")
    scheduled_count = db.query(models.TimetableSlot).filter(
        models.TimetableSlot.teacher_id == obj.teacher_id,
        models.TimetableSlot.subject_id == obj.subject_id,
        models.TimetableSlot.class_group_id == obj.class_group_id,
    ).count()
    resp = AssignmentResponse.model_validate(obj)
    resp.scheduled_count = scheduled_count
    return resp


@app.delete("/assignments/{item_id}", tags=["Assignments"])
def delete_assignment(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin", "teacher"])),
):
    return crud_helpers.delete_one(db, models.Assignment, item_id, "ภาระงานสอน")


@app.post("/assignments/upload-csv", tags=["Assignments"], dependencies=[Depends(rate_limit)])
def upload_assignments_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin", "teacher"])),
):
    """CSV columns: teacher_code, subject_code, class_group_name, periods_per_week.
    Unlike the other bulk-upload endpoints, this one does NOT abort the whole batch
    on a bad row — it resolves each row's human-readable codes to internal IDs and
    skips (with a reason) any row it can't resolve, since real teaching-load exports
    often have a few inconsistent rows mixed into otherwise-good data."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="กรุณาอัปโหลดไฟล์ .csv เท่านั้น")

    contents = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(contents))

    teachers_by_code = {t.code: t.id for t in db.query(models.Teacher).filter(models.Teacher.code.isnot(None)).all()}
    subjects_by_code = {s.code: s.id for s in db.query(models.Subject).all()}
    class_groups_by_name = {c.name: c.id for c in db.query(models.ClassGroup).all()}

    created = 0
    skipped = []
    line_num = 1
    for row in reader:
        line_num += 1
        tcode = (row.get("teacher_code") or "").strip()
        scode = (row.get("subject_code") or "").strip()
        cgname = (row.get("class_group_name") or "").strip()
        periods_raw = (row.get("periods_per_week") or "").strip()

        teacher_id = teachers_by_code.get(tcode)
        subject_id = subjects_by_code.get(scode)
        class_group_id = class_groups_by_name.get(cgname)

        reasons = []
        if not teacher_id:
            reasons.append(f"ไม่พบรหัสครู '{tcode}'")
        if not subject_id:
            reasons.append(f"ไม่พบรหัสวิชา '{scode}'")
        if not class_group_id:
            reasons.append(f"ไม่พบระดับชั้น '{cgname}'")
        try:
            periods = int(periods_raw)
        except ValueError:
            periods = None
            reasons.append(f"จำนวนคาบ/สัปดาห์ไม่ถูกต้อง '{periods_raw}'")

        if reasons:
            skipped.append({"line": line_num, "reason": "; ".join(reasons)})
            continue

        db.add(models.Assignment(
            teacher_id=teacher_id, subject_id=subject_id,
            class_group_id=class_group_id, periods_per_week=periods,
        ))
        created += 1

    db.commit()
    return {
        "message": f"นำเข้าภาระงานสอนสำเร็จ {created} รายการ (ข้าม {len(skipped)} รายการที่หาข้อมูลอ้างอิงไม่เจอ)",
        "created": created,
        "skipped": skipped,
    }


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
    # One query instead of three: fetch any slot at this day+period that
    # matches teacher, room, OR class_group, then figure out which one
    # conflicted in Python — same friendly error messages, 1 round trip.
    candidates = db.query(models.TimetableSlot).filter(
        models.TimetableSlot.day == day,
        models.TimetableSlot.period == period,
        (models.TimetableSlot.teacher_id == teacher_id)
        | (models.TimetableSlot.room_id == room_id)
        | (models.TimetableSlot.class_group_id == class_group_id),
    ).all()

    for slot in candidates:
        if slot.teacher_id == teacher_id:
            raise HTTPException(
                status_code=400,
                detail=f"ครู ID {teacher_id} มีสอนในวัน {day} คาบที่ {period} อยู่แล้ว",
            )
    for slot in candidates:
        if slot.room_id == room_id:
            raise HTTPException(
                status_code=400,
                detail=f"ห้องเรียน ID {room_id} ถูกใช้งานในวัน {day} คาบที่ {period} อยู่แล้ว",
            )
    for slot in candidates:
        if slot.class_group_id == class_group_id:
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
                "teacher": {"id": s.teacher.id, "code": s.teacher.code, "name": s.teacher.name, "email": s.teacher.email} if s.teacher else None,
                "subject": {"id": s.subject.id, "code": s.subject.code, "name": s.subject.name} if s.subject else None,
                "room": {"id": s.room.id, "code": s.room.code, "name": s.room.name, "capacity": s.room.capacity} if s.room else None,
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
        "data": {
            "id": new_slot.id,
            "day": new_slot.day,
            "period": new_slot.period,
            "teacher_id": new_slot.teacher_id,
            "subject_id": new_slot.subject_id,
            "room_id": new_slot.room_id,
            "class_group_id": new_slot.class_group_id,
        },
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
