import sys
import os

# เพิ่ม Path ให้ Python หาโมดูล app เจอ
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import User
from app.auth import get_password_hash

def create_admin():
    db = SessionLocal()
    try:
        # สร้าง Hash รหัสผ่านใหม่
        default_password = "AdminSecretPassword123!"
        hashed_pwd = get_password_hash(default_password)
        
        # ตรวจสอบว่ามี admin ในระบบหรือยัง
        existing_admin = db.query(User).filter(User.username == "admin").first()
        
        if not existing_admin:
            admin_user = User(
                username="admin",
                hashed_password=hashed_pwd,
                role="admin"
            )
            db.add(admin_user)
            print("✅ Created default Admin account successfully!")
        else:
            # หากมีอยู่แล้ว ให้อัปเดตรหัสผ่านใหม่ทับรหัสผ่านเดิมที่ว่างอยู่
            existing_admin.hashed_password = hashed_pwd
            print("🔄 Updated existing Admin password successfully!")
            
        db.commit()
    except Exception as e:
        print(f"❌ Error creating/updating admin: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_admin()