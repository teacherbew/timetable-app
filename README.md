# 🏫 School Timetable API

ระบบ Backend API สำหรับจัดการตารางเรียนตารางสอน พัฒนาด้วย **FastAPI**, **PostgreSQL**, และ **Redis** พร้อมระบบตรวจสอบความขัดแย้งของตารางเรียน (Conflict Detection Engine) และระบบยืนยันตัวตน (RBAC Authentication)

---

## 🚀 Features

* **Data Integrity & Relationships:** กำหนด Foreign Keys และ Not-Null Constraints เชื่อมโยง ครู, วิชา, และห้องเรียน อย่างรัดกุม
* **Conflict Engine:** ตรวจสอบตารางสอนซ้ำซ้อนทั้งแบบรายคาบและไฟล์ CSV (ป้องกันครูสอนซ้อน หรือห้องเรียนถูกใช้ซ้ำ)
* **RBAC Security:** ยืนยันตัวตนด้วย JWT Token แบ่งสิทธิ์การใช้งานชัดเจน (`admin` / `teacher`)
* **Redis Caching:** แคชข้อมูลผลลัพธ์แบบ Dynamic Keys ลดภาระ Database พร้อมระบบ Auto-Flush เมื่อมีการอัปเดตข้อมูล
* **Filter & Pagination:** รองรับการกรองข้อมูลตาม วัน, ครู, ห้องเรียน พร้อมแบ่งหน้าแสดงผล (Pagination)
* **Automated Testing:** มีชุดทดสอบด้วย `pytest` ครอบคลุม Auth, API Structure และ Edge Cases

---

## 🛠️ Tech Stack

* **Framework:** FastAPI (Python 3.11)
* **Database:** PostgreSQL (SQLAlchemy ORM)
* **Cache:** Redis
* **Containerization:** Docker & Docker Compose
* **Testing:** Pytest & TestClient

---

## 🏁 Getting Started

### 1. Clone Project & Start Containers

```bash
git clone [https://github.com/YOUR_USERNAME/timetable-app.git](https://github.com/YOUR_USERNAME/timetable-app.git)
cd timetable-app
docker compose up -d --build