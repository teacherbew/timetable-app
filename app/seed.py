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
        # เช็คว่ามี admin อยู่แล้วหรือยัง
        existing_admin = db.query(User).filter(User.username == "admin").first()
        if not existing_admin:
            hashed_pwd = get_password_hash("AdminSecretPassword123!")
            admin_user = User(
                username="admin",
                password_hash=hashed_pwd,
                role="admin"
            )
            db.add(admin_user)
            db.commit()
            print("✅ Created default Admin account successfully!")
        else:
            print("ℹ️ Admin account already exists.")
    except Exception as e:
        print(f"❌ Error creating admin: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_admin()