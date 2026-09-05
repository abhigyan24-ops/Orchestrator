from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    COMPLETED = "done"
    FAILED = "failed"
    WAITING_QUOTA = "waiting_quota"
    TESTS_FAILED = "tests_failed"


class CredentialStatus(str, Enum):
    AVAILABLE = "available"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class QuotaState(str, Enum):
    AVAILABLE = "available"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class ToolType(str, Enum):
    API_BASED = "api_based"
    IDE_NATIVE = "ide_native"


class QuotaEvent(str, Enum):
    CALL_SUCCESS = "call_success"
    CALL_FAILED = "call_failed"
    QUOTA_EXCEEDED = "quota_exceeded"


class ToolSkill(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_name: str
    model_name: str
    task_category: str
    priority: int
    notes: Optional[str] = None


class Task(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str
    title: str
    category: str
    description: Optional[str] = None
    brief: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    complexity_score: int = 1
    working_branch: Optional[str] = None
    partial_summary: Optional[str] = None
    status: TaskStatus
    assigned_tool: Optional[str] = None
    assigned_model: Optional[str] = None
    depends_on: Optional[int] = None
    repo_url: Optional[str] = None
    branch: Optional[str] = None
    target_folder: Optional[str] = None
    base_branch: str
    pr_url: Optional[str] = None
    result_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ApiCredential(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_name: str
    account_label: str
    api_key: str
    sequence_order: int
    status: CredentialStatus
    tool_type: ToolType


class QuotaStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tool_name: str
    model_name: str
    account_label: Optional[str] = None
    status: QuotaState
    last_checked: Optional[datetime] = None
    reset_at: Optional[datetime] = None
    notes: Optional[str] = None


class QuotaLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_name: str
    model_name: str
    task_id: Optional[int] = None
    event: QuotaEvent
    timestamp: datetime
    raw_response: Optional[str] = None


class ProjectContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    architecture: Optional[str] = None
    progress_log: Optional[str] = None
    handoff_notes: Optional[str] = None
    updated_at: datetime
