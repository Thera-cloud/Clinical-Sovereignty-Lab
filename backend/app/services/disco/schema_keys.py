"""Live schema keys for GEO contracts. Spec v1.5 names are aliases only.

Discoverability never reads `coaches(id)` or `google_credentials`.
Identity is `users.username`. Tokens live in workspace + calendar tables.
"""

from __future__ import annotations

# Spec name → live (table, column). Contract names stay credentials/engagements/
# content_topics/authoring per MASTER §18.2.
SCHEMA_KEYS = {
    "credentials": {
        "identity": ("users", "username"),
        "hardware": ("users", "hardware_id"),
        "class": ("users", "relationship_class"),
        "jurisdiction": ("users", "client_jurisdiction"),
        "vault_sync": ("users", "vault_sync"),
        "credential_rows": ("coach_credentials", "coach_id"),
        "token_workspace": ("google_workspace_connection", "user_id"),
        "token_calendar": ("google_calendar_connection", "user_id"),
    },
    "engagements": {
        "table": ("campaign_engagements", "coach_id"),
        "channel": ("campaign_engagements", "channel"),
        "payload": ("campaign_engagements", "payload"),
        "source": ("campaign_engagements", "source"),
    },
    "content_topics": {
        "v15": ("content_topics", "topic"),
        "coach_flagged": ("disco_content_topics", "coach_id"),
        "flagged_at": ("disco_content_topics", "flagged_at"),
        "source_url": ("disco_content_topics", "source_url"),
        "used_in": ("disco_content_topics", "used_in"),
    },
    "authoring": {
        "table": ("marketing_content", "id"),
        "coach_id": ("marketing_content", "coach_id"),
        "status": ("marketing_content", "status"),
        "slug": ("marketing_content", "slug"),
        "content_type": ("marketing_content", "content_type"),
    },
}

# Spec fiction — raise if disco SQL names these.
FORBIDDEN_TABLES = frozenset({"google_credentials", "coaches"})

# canonical_identity.coach_id and all disco coach_id columns = users.username
IDENTITY_KEY = ("users", "username")


def live_table(pair: tuple[str, str]) -> str:
    return pair[0]


def live_column(pair: tuple[str, str]) -> str:
    return pair[1]


def all_live_tables() -> frozenset[str]:
    tables = set()
    for contract in SCHEMA_KEYS.values():
        for pair in contract.values():
            tables.add(pair[0])
    return frozenset(tables)
