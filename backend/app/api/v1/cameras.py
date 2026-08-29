import uuid
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api import deps
from app.models.user import User
from app.models.camera import Camera, CameraGroup, CameraCalibration, VirtualZone
from app.schemas.camera import (
    CameraCreate, CameraUpdate, CameraResponse,
    VirtualZoneCreate, VirtualZoneResponse
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(
    camera_in: CameraCreate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Register a new surveillance camera in the database.
    """
    existing_res = await db.execute(select(Camera).filter(Camera.name == camera_in.name))
    if existing_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Camera with name '{camera_in.name}' already registered."
        )

    db_obj = Camera(
        id=uuid.uuid4(),
        name=camera_in.name,
        group_id=camera_in.group_id,
        building=camera_in.building,
        floor=camera_in.floor,
        location=camera_in.location,
        latitude=camera_in.latitude,
        longitude=camera_in.longitude,
        direction=camera_in.direction,
        field_of_view=camera_in.field_of_view,
        resolution=camera_in.resolution,
        status=camera_in.status,
        snapshot_path=camera_in.snapshot_path,
        created_at=datetime.now(timezone.utc)
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

@router.get("", response_model=List[CameraResponse])
@router.get("/", response_model=List[CameraResponse])
async def list_cameras(
    building: Optional[str] = None,
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve all registered surveillance cameras with optional filters.
    """
    stmt = select(Camera).options(selectinload(Camera.zones), selectinload(Camera.calibrations))
    if building:
        stmt = stmt.filter(Camera.building == building)
    if status_filter:
        stmt = stmt.filter(Camera.status == status_filter)
    
    stmt = stmt.order_by(Camera.name.asc())
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/{id}", response_model=CameraResponse)
async def get_camera(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Get detailed records and virtual zones for a camera.
    """
    stmt = (
        select(Camera)
        .options(selectinload(Camera.zones), selectinload(Camera.calibrations))
        .filter(Camera.id == id)
    )
    result = await db.execute(stmt)
    camera = result.scalars().first()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found."
        )
    return camera

@router.put("/{id}", response_model=CameraResponse)
async def update_camera(
    id: uuid.UUID,
    camera_in: CameraUpdate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Update field properties of a camera.
    """
    stmt = (
        select(Camera)
        .options(selectinload(Camera.zones), selectinload(Camera.calibrations))
        .filter(Camera.id == id)
    )
    result = await db.execute(stmt)
    camera = result.scalars().first()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found."
        )

    update_data = camera_in.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(camera, field, val)

    await db.commit()
    await db.refresh(camera)
    return camera

@router.delete("/{id}", response_model=dict)
async def delete_camera(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Remove a camera and associated zones/calibrations from index.
    """
    stmt = select(Camera).filter(Camera.id == id)
    result = await db.execute(stmt)
    camera = result.scalars().first()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found."
        )

    await db.delete(camera)
    await db.commit()
    return {"message": "Camera successfully deleted."}

# Virtual Zones management nested under cameras
@router.post("/{id}/zones", response_model=VirtualZoneResponse, status_code=status.HTTP_201_CREATED)
async def create_camera_zone(
    id: uuid.UUID,
    zone_in: VirtualZoneCreate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Add a polygon or line virtual monitoring zone to a camera.
    """
    stmt = select(Camera).filter(Camera.id == id)
    result = await db.execute(stmt)
    camera = result.scalars().first()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found."
        )

    db_obj = VirtualZone(
        id=uuid.uuid4(),
        camera_id=id,
        name=zone_in.name,
        zone_type=zone_in.zone_type,
        geometry_type=zone_in.geometry_type,
        coordinates=zone_in.coordinates,
        created_at=datetime.now(timezone.utc)
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

@router.delete("/{id}/zones/{zone_id}", response_model=dict)
async def delete_camera_zone(
    id: uuid.UUID,
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Delete a virtual zone.
    """
    stmt = select(VirtualZone).filter(VirtualZone.camera_id == id, VirtualZone.id == zone_id)
    result = await db.execute(stmt)
    zone = result.scalars().first()
    if not zone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Zone not found on this camera."
        )

    await db.delete(zone)
    await db.commit()
    return {"message": "Zone successfully deleted."}
