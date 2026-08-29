import asyncio
from sqlalchemy import text
from sqlalchemy.future import select
from app.db.session import engine, SessionLocal
from app.db.base_class import Base

from app.models.user import User
from app.models.video import Video
from app.models.camera import Camera, CameraGroup, CameraCalibration, VirtualZone
from app.models.student import Student, StudentPhoto, StudentFaceSession
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent
from app.models.notification import Notification, NotificationPreference
from app.models.report import Report
from app.models.track import Track, Detection, PersonReid
from app.models.event import Event, EventTrack
from app.models.bulk_import import BulkImportJob
from app.models.face_embedding import StudentFaceEmbedding
from app.models.recognition import StudentRecognitionEvent

from app.core import security

async def seed_users():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Check if role column exists in users table, if not add it
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(50) DEFAULT 'operator'"))
            print("MIGRATION: Added role column to users table")
        except Exception:
            # Column already exists
            pass
    
    async with SessionLocal() as db:
        # Seed requested operator account: admin@campus.edu / Admin@123 / operator
        result = await db.execute(select(User).filter(User.email == "admin@campus.edu"))
        user = result.scalars().first()
        if not user:
            new_user = User(
                email="admin@campus.edu",
                hashed_password=security.get_password_hash("Admin@123"),
                full_name="Campus Operator",
                role="operator",
                is_active=True,
            )
            db.add(new_user)
            await db.commit()
            print("OPERATOR_USER_CREATED: admin@campus.edu")
        else:
            user.hashed_password = security.get_password_hash("Admin@123")
            user.role = "operator"
            user.is_active = True
            await db.commit()
            print("OPERATOR_USER_UPDATED: admin@campus.edu")

if __name__ == "__main__":
    asyncio.run(seed_users())

