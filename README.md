# 🏫 School Timetable API

ระบบ Backend API สำหรับจัดการตารางเรียนตารางสอน พัฒนาด้วย **FastAPI**, **PostgreSQL**, และ **Redis** พร้อมระบบตรวจสอบความขัดแย้งของตารางเรียน (Conflict Detection Engine) และระบบยืนยันตัวตน (RBAC Authentication)

---

## 🚀 Features

* **Data Integrity & Relationships:** กำหนด Foreign Keys และ Not-Null Constraints เชื่อมโยง ครู, วิชา, และห้องเรียน อย่างรัดกุม
* **Conflict Engine:** ตรวจสอบตารางสอนซ้ำซ้อนทั้งแบบรายคาบและไฟล์ CSV (ป้องกันครูสอนซ้อน หรือห้องเรียนถูกใช้ซ้ำ)
* **RBAC Security:** ยืนยันตัวตนด้วย JWT Token แบ่งสิทธิ์การใช้งานชัดเจน (`admin` / `teacher`)
* **Redis Caching:** แคชข้อมูลผลลัพธ์แบบ Dynamic Keys ลดภาระ Database พร้อมระบบ Auto-Flush เมื่อมีการอัปเดตข้อมูล
* **Rate Limiting:** จำกัดจำนวน request ต่อ IP บน endpoint ที่สำคัญ (login, upload CSV) ผ่าน Redis
* **Filter & Pagination:** รองรับการกรองข้อมูลตาม วัน, ครู, ห้องเรียน พร้อมแบ่งหน้าแสดงผล (Pagination)
* **Automated Testing:** มีชุดทดสอบด้วย `pytest` ครอบคลุม Auth, API Structure และ Edge Cases

---

## 🛠️ Tech Stack

* **Framework:** FastAPI (Python 3.11)
* **Database:** PostgreSQL (SQLAlchemy ORM)
* **Cache / Rate limiting:** Redis
* **Containerization:** Docker & Docker Compose
* **Testing:** Pytest & TestClient

---

## 🏁 Getting Started (local / docker-compose)

### 1. Clone and configure environment

```bash
git clone https://github.com/YOUR_USERNAME/timetable-app.git
cd timetable-app
cp .env.example .env
```

Open `.env` and fill in real values — at minimum set a strong `SECRET_KEY` and
a real `POSTGRES_PASSWORD`. `.env` is gitignored and must never be committed.

### 2. Start everything

```bash
docker compose up -d --build
```

This starts Postgres, Redis, and the API on `http://localhost:8000`.

### 3. Create the database schema

The app creates tables automatically on startup via `Base.metadata.create_all()`,
so no extra step is needed for a first run. If you'd rather manage schema
changes through Alembic migrations instead (recommended once this app grows),
remove the `create_all()` call in `app/main.py` and run:

```bash
docker compose exec web alembic upgrade head
```

### 4. Seed an admin user and sample data

```bash
docker compose exec web python -m app.seed
docker compose exec web python -m app.import_csv
```

`app.seed` reads the admin password from `ADMIN_DEFAULT_PASSWORD` in `.env` —
set it before seeding, and change it again after first login in production.

### 5. Explore the API

Interactive docs: `http://localhost:8000/docs`

---

## ☁️ Deploying (e.g. Render)

* Set environment variables in your platform's dashboard (not in a committed
  `.env` file): `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
  `REDIS_HOST`, `REDIS_PORT`, `ADMIN_DEFAULT_PASSWORD`.
* For the database: if you attach a managed Postgres instance on Render, it
  usually provides `DATABASE_URL` automatically — the app picks that up
  directly. Otherwise set `POSTGRES_HOST` / `POSTGRES_USER` /
  `POSTGRES_PASSWORD` / `POSTGRES_DB` and the app will build the connection
  string itself.
* Run `python -m app.seed` once (e.g. via a one-off shell/job on the platform)
  to create the admin account, using a real, unique `ADMIN_DEFAULT_PASSWORD`.

## 🔒 Security notes

* Never commit `.env`. Only `.env.example` (placeholders) should be in git.
* Rotate any credential that was ever committed to git history, even if you
  later removed it — it's still recoverable from old commits until you rewrite
  history (`git filter-repo` / BFG) and force-push.
* Change `ADMIN_DEFAULT_PASSWORD` after first login in any real deployment.
