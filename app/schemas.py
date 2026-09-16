from typing import List, Optional

from pydantic import BaseModel


# --- Teacher Schemas ---
class TeacherBase(BaseModel):
    name: str
    email: str


class TeacherCreate(TeacherBase):
    pass


class TeacherResponse(TeacherBase):
    id: int

    class Config:
        from_attributes = True


# --- Subject Schemas ---
class SubjectBase(BaseModel):
    code: str
    name: str


class SubjectCreate(SubjectBase):
    pass


class SubjectResponse(SubjectBase):
    id: int

    class Config:
        from_attributes = True


# --- Room Schemas ---
class RoomBase(BaseModel):
    name: str
    capacity: int


class RoomCreate(RoomBase):
    pass


class RoomResponse(RoomBase):
    id: int

    class Config:
        from_attributes = True


# --- TimetableSlot Schemas ---
class TimetableSlotBase(BaseModel):
    day: str
    period: int
    teacher_id: int
    subject_id: int
    room_id: int


class TimetableSlotCreate(TimetableSlotBase):
    pass


class TimetableSlotResponse(BaseModel):
    id: int
    day: str
    period: int
    teacher: Optional[TeacherResponse] = None
    subject: Optional[SubjectResponse] = None
    room: Optional[RoomResponse] = None

    class Config:
        from_attributes = True


# --- Wrapper for paginated schedule responses ---
class ScheduleDataContent(BaseModel):
    total_items: int
    page: int = 1
    limit: int = 10
    total_pages: int = 1
    items: List[TimetableSlotResponse]


class ScheduleResponseWrapper(BaseModel):
    source: str
    data: ScheduleDataContent
