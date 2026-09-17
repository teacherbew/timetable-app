from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class Teacher(Base):
    __tablename__ = "teachers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)


class Subject(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)


class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="teacher", nullable=False)


class ClassGroup(Base):
    """ระดับชั้น/ห้องเรียนนักเรียน เช่น ม.1/1, ป.6/2 — กลุ่มนักเรียนที่เรียนตารางร่วมกัน
    (คนละอย่างกับ Room ซึ่งคือห้องเรียนทางกายภาพ)"""
    __tablename__ = "class_groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)  # เช่น "ม.1/1"
    level = Column(String, nullable=False)  # เช่น "ม.1"


class TimetableSlot(Base):
    __tablename__ = "timetable_slots"
    id = Column(Integer, primary_key=True, index=True)
    day = Column(String, nullable=False)
    period = Column(Integer, nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    # nullable=True at the DB level on purpose: this column is added to an
    # already-deployed table via ALTER TABLE, so old rows won't have a value.
    # New slots are required to set it (enforced in the Pydantic schema).
    class_group_id = Column(Integer, ForeignKey("class_groups.id"), nullable=True)

    teacher = relationship("Teacher")
    subject = relationship("Subject")
    room = relationship("Room")
    class_group = relationship("ClassGroup")
