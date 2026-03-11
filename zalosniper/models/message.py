from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Message:
    id: Optional[int]
    group_name: str
    sender: str
    content: str
    timestamp: datetime
    zalo_message_id: Optional[str] = None
    processed: bool = False
    created_at: Optional[datetime] = None
