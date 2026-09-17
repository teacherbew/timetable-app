import csv

from app.database import SessionLocal
from app.models import ClassGroup, Room, Subject, Teacher, TimetableSlot


def seed_dependencies(db):
    if db.query(Teacher).count() == 0:
        db.add_all([
            Teacher(id=1, name="Dr. Smith", email="smith@school.com"),
            Teacher(id=2, name="Prof. Johnson", email="johnson@school.com"),
            Teacher(id=3, name="Ajarn Somchai", email="somchai@school.com"),
        ])

    if db.query(Subject).count() == 0:
        db.add_all([
            Subject(id=1, code="CS101", name="Computer Science 101"),
            Subject(id=2, code="CS102", name="Database Systems"),
            Subject(id=3, code="MATH101", name="Calculus I"),
        ])

    if db.query(Room).count() == 0:
        db.add_all([
            Room(id=1, name="Lab 101", capacity=30),
            Room(id=2, name="Room 202", capacity=40),
        ])

    if db.query(ClassGroup).count() == 0:
        db.add_all([
            ClassGroup(id=1, name="ม.1/1", level="ม.1"),
            ClassGroup(id=2, name="ม.1/2", level="ม.1"),
        ])

    db.commit()


def import_csv_data(csv_path: str = "timetable.csv"):
    db = SessionLocal()
    try:
        seed_dependencies(db)

        with open(csv_path, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            slots_to_add = [
                TimetableSlot(
                    day=row["day"],
                    period=int(row["period"]),
                    teacher_id=int(row["teacher_id"]),
                    subject_id=int(row["subject_id"]),
                    room_id=int(row["room_id"]),
                    class_group_id=int(row["class_group_id"]),
                )
                for row in reader
            ]

            db.add_all(slots_to_add)
            db.commit()
            print(f"✅ นำเข้าข้อมูลตารางเรียนสำเร็จทั้งหมด {len(slots_to_add)} รายการ!")

    except Exception as e:
        db.rollback()
        print(f"❌ เกิดข้อผิดพลาดในการนำเข้าข้อมูล: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    import_csv_data()
