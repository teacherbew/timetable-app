import json
import csv
import io
from typing import Optional
import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional
from app import models
from app.database import get_db, engine
from app.redis_client import redis_client
from app.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
    require_roles
)

# สร้างตารางใน DB อัตโนมัติหากยังไม่มี
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="School Timetable API")


@app.get("/")
def read_root():
    return {"message": "Welcome to School Timetable API"}


# ----------------------------------------------------
# AUTHENTICATION
# ----------------------------------------------------
@app.post("/login", tags=["Auth"])
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    # เปลี่ยนเป็น user.hashed_password ตรงนี้
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role}
    )
    return {"access_token": access_token, "token_type": "bearer"}


# ----------------------------------------------------
# TIMETABLE MANAGEMENT
# ----------------------------------------------------

# ดึงข้อมูลตารางเรียน (ค้นหา + แบ่งหน้า + Dynamic Redis Cache)
@app.get("/timetable/", tags=["Timetable"])
def get_timetable(
    day: Optional[str] = Query(None, description="วัน เช่น Monday, Tuesday"),
    teacher_id: Optional[int] = Query(None, description="ID ครู"),
    room_id: Optional[int] = Query(None, description="ID ห้อง"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    # 1. ทำความสะอาดค่าพารามิเตอร์ (ตัดค่าขยะ "" หรือ "string" จาก Swagger UI)
    clean_day = day.strip() if day and day.strip() and day.strip().lower() != "string" else None
    clean_teacher = teacher_id if teacher_id is not None and teacher_id > 0 else None
    clean_room = room_id if room_id is not None and room_id > 0 else None

    # 2. สร้าง Cache Key จากค่าที่ Clean แล้ว
    cache_key = f"timetable:day={clean_day}:teacher={clean_teacher}:room={clean_room}:page={page}:limit={limit}"
    
    # 3. เช็ค Redis Cache
    try:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            return {"source": "cache", "data": json.loads(cached_data)}
    except Exception as e:
        print(f"Redis Cache Error: {e}")

    # 4. Query ข้อมูลจาก Database
    query = db.query(models.TimetableSlot)

    if clean_day:
        query = query.filter(models.TimetableSlot.day.ilike(clean_day))
    if clean_teacher:
        query = query.filter(models.TimetableSlot.teacher_id == clean_teacher)
    if clean_room:
        query = query.filter(models.TimetableSlot.room_id == clean_room)

    # 5. คำนวณแบ่งหน้า (Pagination)
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
                "teacher_id": s.teacher_id,
                "subject_id": s.subject_id,
                "room_id": s.room_id
            }
            for s in slots
        ]
    }

    # 6. บันทึกลง Redis Cache (60 วินาที)
    try:
        redis_client.set(cache_key, json.dumps(result), ex=60)
    except Exception as e:
        print(f"Redis Set Error: {e}")

    return {"source": "database", "data": result}
# เพิ่มคาบเรียนทีละ 1 รายการ (พร้อมเช็คคาบซ้ำ)
@app.post("/timetable/", tags=["Timetable"])
def create_timetable_slot(
    slot_data: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin", "teacher"]))
):
    day = slot_data.get("day")
    period = int(slot_data.get("period"))
    teacher_id = int(slot_data.get("teacher_id"))
    subject_id = int(slot_data.get("subject_id"))
    room_id = int(slot_data.get("room_id"))

    # เช็ค 1: ครูติดสอนในคาบนี้หรือยัง
    teacher_busy = db.query(models.TimetableSlot).filter(
        models.TimetableSlot.day == day,
        models.TimetableSlot.period == period,
        models.TimetableSlot.teacher_id == teacher_id
    ).first()
    if teacher_busy:
        raise HTTPException(
            status_code=400, 
            detail=f"ครู ID {teacher_id} มีสอนในวัน {day} คาบที่ {period} อยู่แล้ว"
        )

    # เช็ค 2: ห้องเรียนถูกใช้ในคาบนี้หรือยัง
    room_busy = db.query(models.TimetableSlot).filter(
        models.TimetableSlot.day == day,
        models.TimetableSlot.period == period,
        models.TimetableSlot.room_id == room_id
    ).first()
    if room_busy:
        raise HTTPException(
            status_code=400, 
            detail=f"ห้องเรียน ID {room_id} ถูกใช้งานในวัน {day} คาบที่ {period} อยู่แล้ว"
        )

    try:
        new_slot = models.TimetableSlot(
            day=day,
            period=period,
            teacher_id=teacher_id,
            subject_id=subject_id,
            room_id=room_id
        )
        db.add(new_slot)
        db.commit()
        db.refresh(new_slot)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400, 
            detail="ไม่สามารถสร้างได้: ตรวจสอบ teacher_id, subject_id, room_id ว่ามีในระบบหรือไม่"
        )

    try:
        redis_client.flushdb()
    except Exception:
        pass

    return {"message": f"สร้างคาบเรียนสำเร็จโดย {current_user.username}", "data": new_slot}


# นำเข้าไฟล์ CSV (พร้อมเช็คคาบซ้ำทั้งใน DB และในไฟล์ CSV)
@app.post("/timetable/upload-csv", tags=["Timetable"])
def upload_timetable_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin", "teacher"]))
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="กรุณาอัปโหลดไฟล์ .csv เท่านั้น")
    
    contents = file.file.read().decode("utf-8")
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
        day = row["day"]
        period = int(row["period"])
        teacher_id = int(row["teacher_id"])
        subject_id = int(row["subject_id"])
        room_id = int(row["room_id"])

        teacher_key = (day, period, teacher_id)
        room_key = (day, period, room_id)

        if teacher_key in db_teacher_slots:
            raise HTTPException(
                status_code=400,
                detail=f"ข้อมูลบรรทัดที่ {line_num} ขัดแย้ง: ครู ID {teacher_id} มีสอนในวัน {day} คาบที่ {period} อยู่แล้ว"
            )
        
        if room_key in db_room_slots:
            raise HTTPException(
                status_code=400,
                detail=f"ข้อมูลบรรทัดที่ {line_num} ขัดแย้ง: ห้อง ID {room_id} ถูกใช้งานในวัน {day} คาบที่ {period} อยู่แล้ว"
            )

        db_teacher_slots.add(teacher_key)
        db_room_slots.add(room_key)
        
        slot = models.TimetableSlot(
            day=day,
            period=period,
            teacher_id=teacher_id,
            subject_id=subject_id,
            room_id=room_id
        )
        new_slots.append(slot)

    try:
        db.add_all(new_slots)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400, 
            detail="นำเข้าไม่สำเร็จ: มี teacher_id, subject_id หรือ room_id ใน CSV ที่ไม่มีอยู่ในระบบ"
        )
    
    try:
        redis_client.flushdb()
    except Exception:
        pass
        
    return {
        "message": f"นำเข้าข้อมูลสำเร็จ {len(new_slots)} รายการ",
        "imported_by": current_user.username
    }