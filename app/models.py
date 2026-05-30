from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int

class StoreEvent(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: Literal[
        "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", 
        "ZONE_DWELL", "BILLING_QUEUE_JOIN", 
        "BILLING_QUEUE_ABANDON", "REENTRY"
    ]
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int
    is_staff: bool
    confidence: float
    metadata: EventMetadata
