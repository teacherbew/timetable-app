from pydantic import BaseModel

class TeacherBase(BaseModel):
    name: str
    email: str

class TeacherCreate(TeacherBase):
    pass

class TeacherResponse(TeacherBase):
    id: int
    class Config:
        from_attributes = True

class SubjectBase(BaseModel):
    code: str
    name: str

class SubjectCreate(SubjectBase):
    pass

class SubjectResponse(SubjectBase):
    id: int
    class Config:
        from_attributes = True

class RoomBase(BaseModel):
    name: str
    capacity: int

class RoomCreate(RoomBase):
    pass

class RoomResponse(RoomBase):
    id: int
    class Config:
        from_attributes = True

class TimetableSlotBase(BaseModel):
    day: str
    period: int
    teacher_id: int
    subject_id: int
    room_id: int

class TimetableSlotCreate(TimetableSlotBase):
    pass

class TimetableSlotResponse(TimetableSlotBase):
    id: int
    class Config:
        from_attributes = True