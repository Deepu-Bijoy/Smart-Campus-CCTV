import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional

# CameraGroup Schemas
class CameraGroupBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=255)

class CameraGroupCreate(CameraGroupBase):
    pass

class CameraGroupResponse(CameraGroupBase):
    id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True

# VirtualZone Schemas
class VirtualZoneBase(BaseModel):
    name: str = Field(..., max_length=100)
    zone_type: str = Field(..., description="Fence, Restricted Area, Gate, Road, Parking")
    geometry_type: str = Field(..., description="polygon, line")
    coordinates: str = Field(..., description="JSON-serialized coordinates list")

class VirtualZoneCreate(VirtualZoneBase):
    pass

class VirtualZoneResponse(VirtualZoneBase):
    id: uuid.UUID
    camera_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True

# CameraCalibration Schemas
class CameraCalibrationBase(BaseModel):
    calibration_matrix: str = Field(..., description="JSON-serialized calibration metrics")

class CameraCalibrationCreate(CameraCalibrationBase):
    pass

class CameraCalibrationResponse(CameraCalibrationBase):
    id: uuid.UUID
    camera_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True

# Camera Schemas
class CameraBase(BaseModel):
    name: str = Field(..., max_length=100)
    group_id: Optional[uuid.UUID] = None
    building: str = Field(..., max_length=100)
    floor: int
    location: str = Field(..., max_length=255)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    direction: str = Field(..., max_length=50)
    field_of_view: Optional[float] = None
    resolution: str = Field(..., max_length=50)
    status: str = Field("active", max_length=50)
    snapshot_path: Optional[str] = None

class CameraCreate(CameraBase):
    pass

class CameraUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    group_id: Optional[uuid.UUID] = None
    building: Optional[str] = Field(None, max_length=100)
    floor: Optional[int] = None
    location: Optional[str] = Field(None, max_length=255)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    direction: Optional[str] = Field(None, max_length=50)
    field_of_view: Optional[float] = None
    resolution: Optional[str] = Field(None, max_length=50)
    status: Optional[str] = Field(None, max_length=50)
    snapshot_path: Optional[str] = None

class CameraResponse(CameraBase):
    id: uuid.UUID
    created_at: datetime
    zones: List[VirtualZoneResponse] = []
    calibrations: List[CameraCalibrationResponse] = []

    class Config:
        from_attributes = True
