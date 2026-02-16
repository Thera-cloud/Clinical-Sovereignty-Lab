"""
SOVEREIGN VAULT — Pydantic Models
Data contracts for the Sovereign Vault: folders, items, transfer crystals,
and activity. B1 Sovereign Sanctuary.
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

class ContentType(str, Enum):
    """Recognized vault item content types."""
    CONVERSATION = "conversation"
    UPLOAD_IMAGE = "upload_image"
    UPLOAD_DOCUMENT = "upload_document"
    NEVEDAL_REPORT = "nevedal_report"
    FORESIGHT_REPORT = "foresight_report"
    COHERENCE_SNAPSHOT = "coherence_snapshot"
    ARCHIVIST_CHAPTER = "archivist_chapter"
    FAMILY_SESSION = "family_session"
    FAMILY_PHOTO = "family_photo"
    TRANSFER_CRYSTAL = "transfer_crystal"
    TRANSFER_RAW = "transfer_raw"
    TRANSFER_CONVERSATION = "transfer_conversation"
    LEGACY_LETTER = "legacy_letter"
    DREAM_ENTRY = "dream_entry"


# =============================================================================
# VAULT FOLDER
# =============================================================================

class VaultFolder(BaseModel):
    """A folder in the member's vault hierarchy."""
    id: UUID = Field(default_factory=uuid4)
    member_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=64)
    parent_id: Optional[UUID] = None
    icon: str = Field(default="📁", max_length=10)
    color: Optional[str] = Field(default=None, max_length=7)
    is_system: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    item_count: int = 0
    sort_order: int = 0


# =============================================================================
# VAULT ITEM
# =============================================================================

class VaultItem(BaseModel):
    """A single item stored in the Sovereign Vault."""
    id: UUID = Field(default_factory=uuid4)
    member_id: str = Field(..., min_length=1, max_length=255)
    folder_id: Optional[UUID] = None
    content_type: ContentType = Field(...)
    filename: Optional[str] = Field(default=None, max_length=255)
    display_name: str = Field(..., min_length=1, max_length=255)
    blob_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    size_bytes: int = 0
    mime_type: Optional[str] = Field(default=None, max_length=100)
    extracted_text_preview: Optional[str] = None
    page_count: Optional[int] = None
    dimensions: Optional[Dict[str, Any]] = None
    duration_seconds: Optional[float] = None
    session_id: Optional[str] = Field(default=None, max_length=255)
    coherence_at_creation: Optional[float] = None
    themes: List[Any] = Field(default_factory=list)
    annotations: List[Any] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    uploaded_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    last_discussed_at: Optional[datetime] = None
    moved_at: Optional[datetime] = None
    starred: bool = False
    is_legacy: bool = False
    is_shared_family: bool = False
    ttl_seconds: Optional[int] = None
    content_hash: Optional[str] = Field(default=None, max_length=64)


# =============================================================================
# TRANSFER CRYSTAL
# =============================================================================

class TransferCrystal(BaseModel):
    """Crystallized conversation data imported from another platform."""
    id: UUID = Field(default_factory=uuid4)
    member_id: str = Field(..., min_length=1, max_length=255)
    source_platform: str = Field(..., min_length=1, max_length=50)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    conversation_count: int = 0
    message_count: int = 0
    date_range_start: Optional[str] = Field(default=None, max_length=50)
    date_range_end: Optional[str] = Field(default=None, max_length=50)
    crystal: Dict[str, Any] = Field(default_factory=dict)
    version: str = Field(default="1.0", max_length=10)
    processing_time_seconds: Optional[float] = None
    token_cost: float = 0.0


# =============================================================================
# VAULT ACTIVITY
# =============================================================================

class VaultActivity(BaseModel):
    """Audit log entry for vault actions."""
    id: UUID = Field(default_factory=uuid4)
    member_id: str = Field(..., min_length=1, max_length=255)
    action: str = Field(..., min_length=1, max_length=50)
    item_id: Optional[UUID] = None
    folder_id: Optional[UUID] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# STATS & API MODELS
# =============================================================================

class VaultStats(BaseModel):
    """Stats for the vault stats endpoint."""
    total_items: int = Field(default=0, description="Total number of items in vault")
    total_size_bytes: int = Field(default=0, description="Total storage used")
    storage_limit_bytes: int = Field(default=0, description="Storage limit for member tier")
    usage_percent: float = Field(default=0.0, ge=0.0, le=100.0, description="Storage usage percentage")
    folder_count: int = Field(default=0, description="Number of folders")
    folder_limit: int = Field(default=0, description="Folder limit for member tier")
    breakdown: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per content-type counts/sizes"
    )


class PreviewData(BaseModel):
    """Preview payload for vault item picker UI."""
    type: str = Field(..., description="Preview type (e.g. text, image, pdf)")
    display_content: str = Field(default="", description="Content to display in preview")
    metadata_shown: Dict[str, Any] = Field(default_factory=dict, description="Metadata to display")
    accept_action: Optional[str] = Field(default=None, description="Optional action when accepting")


class VaultSuggestion(BaseModel):
    """AI-suggested vault item with confidence and prompt."""
    item_id: UUID = Field(...)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0–1")
    reason: str = Field(..., description="Human-readable reason for suggestion")
    suggested_prompt: Optional[str] = Field(default=None, description="Pre-filled prompt to discuss with Nate")
