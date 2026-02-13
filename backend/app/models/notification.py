"""
SOVEREIGN SWARM — Notification Models
Approval notifications via SendGrid email + Twilio SMS (Code Guidelines Section III / 6.1).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# =============================================================================

class NotificationChannel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    BOTH = "both"
    PUSH = "push"        # Future mobile push
    IN_APP = "in_app"    # Dashboard notification


class NotificationStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    REPLIED = "replied"


# =============================================================================
# APPROVAL NOTIFICATION
# =============================================================================

class ApprovalNotification(BaseModel):
    """Outbound notification requesting approval for a strategy proposal."""
    notification_id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    proposal_title: str
    proposal_summary: str
    risk_level: str = "medium"
    auto_execute_at: Optional[datetime] = None

    # Delivery
    channel: NotificationChannel = NotificationChannel.BOTH
    recipient_email: Optional[str] = None
    recipient_phone: Optional[str] = None
    status: NotificationStatus = NotificationStatus.QUEUED

    # SendGrid
    sendgrid_message_id: Optional[str] = None
    email_template_data: Dict[str, Any] = Field(default_factory=dict)

    # Twilio
    twilio_sid: Optional[str] = None
    sms_body: Optional[str] = None  # 160-char max

    # Timestamps
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# APPROVAL RESPONSE
# =============================================================================

class ApprovalResponse(BaseModel):
    """Inbound response to an approval notification."""
    response_id: UUID = Field(default_factory=uuid4)
    notification_id: UUID
    proposal_id: UUID
    channel: NotificationChannel
    decision: str  # APPROVE | HOLD | REJECT | MODIFY
    modifier_text: Optional[str] = None  # For MODIFY responses
    raw_message: str = ""  # Original SMS/email body
    parsed_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)
