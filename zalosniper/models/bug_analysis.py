from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


class BugStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    TASK_ONLY = "task_only"
    DONE = "done"
    ERROR = "error"


@dataclass
class BugAnalysis:
    id: Optional[int]
    message_ids: List[int]
    group_name: str
    status: BugStatus = BugStatus.PENDING
    repo_owner: Optional[str] = None
    repo_name: Optional[str] = None
    repo_selection_reason: Optional[str] = None   # "matched" | "ambiguous"
    claude_summary: Optional[str] = None
    root_cause: Optional[str] = None
    proposed_fix: Optional[str] = None
    code_patch: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    op_work_package_id: Optional[int] = None
    op_work_package_url: Optional[str] = None
    telegram_message_id: Optional[int] = None
    approved_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
