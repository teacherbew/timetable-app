import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_timetable_structure():
    """ทดสอบว่า Endpoint GET /timetable/ ทำงานและส่งโครงสร้างถูกต้อง"""
    response = client.get("/timetable/")
    assert response.status_code == 200
    res_data = response.json()
    assert "source" in res_data
    assert "data" in res_data
    assert "items" in res_data["data"]


def test_upload_csv_unauthorized():
    """ทดสอบว่าหากไม่ Login จะไม่สามารถอัปโหลด CSV ได้ (ต้องได้ 401)"""
    response = client.post("/timetable/upload-csv")
    assert response.status_code == 401


def test_login_and_access():
    """ทดสอบระบบ Login ด้วยบัญชี Admin (ต้องรัน `python -m app.seed` ก่อน
    และรัน pytest ด้วย ADMIN_DEFAULT_PASSWORD ตัวเดียวกับตอน seed)"""
    admin_password = os.getenv("ADMIN_DEFAULT_PASSWORD", "changeme123")
    login_res = client.post(
        "/login",
        data={"username": "admin", "password": admin_password},
    )
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()
