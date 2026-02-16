"""
Sovereign Vault — File upload pipeline (B2), security layer (B6), and tier entitlements (B7).

Provides:
- FileProcessor: MIME validation, extraction, thumbnails
- VaultBlobManager: Quarantine → clean → permanent storage
- VaultOperations: Folder/item CRUD, search, stats, activity
- AutoFiler: Auto-file uploads to correct subfolders
- TransferCrystalBuilder: Transfer Crystal generation
- FileContentSentinel: Content security scanning
- DocumentSectionParser, OrgSessionManager, OrganizerMode: Nate Organizer
"""

from app.services.vault.file_processor import FileProcessor, ProcessedFile
from app.services.vault.blob_manager import VaultBlobManager
from app.services.vault.vault_operations import VaultOperations
from app.services.vault.auto_filer import AutoFiler
from app.services.vault.content_sentinel_file import FileContentSentinel, ScanResult
from app.services.vault.transfer_crystal import TransferCrystalBuilder

# Lazy imports for document_organizer to avoid pulling in asyncpg/httpx
# when only lightweight vault classes are needed.

__all__ = [
    "FileProcessor",
    "ProcessedFile",
    "VaultBlobManager",
    "VaultOperations",
    "AutoFiler",
    "TransferCrystalBuilder",
    "FileContentSentinel",
    "ScanResult",
    "DocumentSectionParser",
    "OrgSessionManager",
    "OrganizerMode",
]


def __getattr__(name):
    """Lazy-load document_organizer classes on first access."""
    _organizer_classes = {"DocumentSectionParser", "OrgSessionManager", "OrganizerMode"}
    if name in _organizer_classes:
        from app.services.vault.document_organizer import (  # noqa: F811
            DocumentSectionParser,
            OrgSessionManager,
            OrganizerMode,
        )
        _map = {
            "DocumentSectionParser": DocumentSectionParser,
            "OrgSessionManager": OrgSessionManager,
            "OrganizerMode": OrganizerMode,
        }
        return _map[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
