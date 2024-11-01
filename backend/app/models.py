# backend/app/models.py
from pydantic import BaseModel
from typing import Optional

TASK_COMPLETE_CHANNEL = 'task_complete'


class TaskCompleteMessage(BaseModel):
    task_id: str
    status: str
    error: Optional[str] = None


class WebSocketNotificationMessage(BaseModel):
    task_id: str
    status: str
    upload_id: Optional[str] = None
    result: Optional[str] = None
