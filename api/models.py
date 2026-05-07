from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    ollama: bool
    db: str
    version: str = "1.0.0"


class ImageRecord(BaseModel):
    id: int
    file_path: str
    file_name: Optional[str]
    shoot_id: Optional[int]
    imported_at: Optional[datetime]
    blur_score: Optional[float]
    exposure_score: Optional[float]
    is_duplicate: Optional[bool]
    pass1_status: Optional[str]
    nima_composite: Optional[float]
    genre: Optional[str]
    mood: Optional[str]
    quality_score: Optional[float]
    portfolio_worthy: Optional[bool]
    content_ready: Optional[bool]
    tags: Optional[str]
    social_queue: Optional[bool]


class PipelineJobRecord(BaseModel):
    id: int
    job_type: str
    shoot_id: Optional[int]
    image_id: Optional[int]
    status: str
    priority: int
    attempts: int
    error: Optional[str]
    queued_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
