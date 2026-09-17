import csv
import io

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def list_all(db: Session, model):
    return db.query(model).order_by(model.id).all()


def create_one(db: Session, model, data: dict):
    obj = model(**data)
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="สร้างไม่สำเร็จ: ข้อมูลนี้อาจซ้ำกับที่มีอยู่แล้ว (เช่น ชื่อ/รหัส/อีเมลซ้ำ)",
        )
    db.refresh(obj)
    return obj


def update_one(db: Session, model, item_id: int, data: dict, label: str):
    obj = db.query(model).filter(model.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"ไม่พบ{label} ID {item_id}")
    for key, value in data.items():
        setattr(obj, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="แก้ไขไม่สำเร็จ: ข้อมูลนี้อาจซ้ำกับที่มีอยู่แล้ว",
        )
    db.refresh(obj)
    return obj


def delete_one(db: Session, model, item_id: int, label: str):
    obj = db.query(model).filter(model.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"ไม่พบ{label} ID {item_id}")
    try:
        db.delete(obj)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"ลบไม่สำเร็จ: {label}นี้ถูกใช้อยู่ในตารางสอนแล้ว ต้องลบคาบเรียนที่เกี่ยวข้องก่อน",
        )
    return {"message": f"ลบ{label} ID {item_id} สำเร็จ"}


def bulk_upload_csv(db: Session, model, create_schema, file: UploadFile, label: str):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="กรุณาอัปโหลดไฟล์ .csv เท่านั้น")

    contents = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(contents))

    new_objects = []
    line_num = 1
    for row in reader:
        line_num += 1
        try:
            validated = create_schema(**row)
        except ValidationError as e:
            raise HTTPException(
                status_code=400,
                detail=f"ข้อมูล{label}บรรทัดที่ {line_num} ไม่ถูกต้อง: {e}",
            )
        new_objects.append(model(**validated.model_dump()))

    try:
        db.add_all(new_objects)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"นำเข้าไม่สำเร็จ: มี{label}ในไฟล์ที่ซ้ำกับข้อมูลเดิม (ตรวจสอบชื่อ/รหัส/อีเมลซ้ำ)",
        )

    return {"message": f"นำเข้า{label}สำเร็จ {len(new_objects)} รายการ"}
