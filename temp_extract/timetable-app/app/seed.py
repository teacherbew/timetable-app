import os
import sys

# Make sure Python can find the `app` package when this script is run directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth import get_password_hash
from app.database import SessionLocal
from app.models import User

# Change this via the ADMIN_DEFAULT_PASSWORD env var before running in any
# shared/production environment — don't rely on the fallback below.
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD", "changeme123")


def create_admin():
    db = SessionLocal()
    try:
        hashed_pwd = get_password_hash(DEFAULT_ADMIN_PASSWORD)
        existing_admin = db.query(User).filter(User.username == "admin").first()

        if not existing_admin:
            admin_user = User(username="admin", hashed_password=hashed_pwd, role="admin")
            db.add(admin_user)
            print("✅ Created default Admin account successfully!")
        else:
            existing_admin.hashed_password = hashed_pwd
            print("🔄 Updated existing Admin password successfully!")

        db.commit()

        if DEFAULT_ADMIN_PASSWORD == "changeme123":
            print("⚠️  Using the fallback admin password. Set ADMIN_DEFAULT_PASSWORD before deploying anywhere shared.")
    except Exception as e:
        print(f"❌ Error creating/updating admin: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
