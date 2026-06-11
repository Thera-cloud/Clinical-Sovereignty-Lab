"""
Database pool shim.

The canonical asyncpg pool lives in app.main (get_db_pool). Some modules
(e.g. patient_sovereignty_service) import `from app.database import
get_db_pool`. Importing app.main at module level would be circular —
main.py mounts the routers that import those services — so the import
is deferred to call time, when app.main is fully loaded.
"""

import asyncpg


async def get_db_pool() -> asyncpg.Pool:
    from app.main import get_db_pool as _main_get_db_pool

    return await _main_get_db_pool()
