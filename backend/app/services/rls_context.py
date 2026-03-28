"""
RLS Context — Per-Request Row Level Security for asyncpg

Uses Python contextvars to carry the authenticated user's identity through
async call chains. The RLSPoolWrapper injects these values as PostgreSQL
session variables (app.acting_username, app.acting_hardware_id, app.acting_role)
on every pool.acquire() and pool.fetch/execute/fetchrow/fetchval call.

This makes RLS policies transparent to application code — endpoints continue
calling pool.acquire() as before, but each connection is scoped to the
authenticated user's rows.

Usage:
    # In auth middleware / dependency:
    set_rls_context(username='alice', hardware_id='HW123', role='CLIENT')

    # For background agents (cross-user queries):
    set_rls_admin()

    # Wrap pool at startup:
    pool = await asyncpg.create_pool(...)
    rls_pool = RLSPoolWrapper(pool)
    app.state.db_pool = rls_pool  # drop-in replacement
"""

import contextvars
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_rls_username = contextvars.ContextVar('rls_username', default='')
_rls_hardware_id = contextvars.ContextVar('rls_hardware_id', default='')
_rls_role = contextvars.ContextVar('rls_role', default='')

_SET_SQL = (
    "SELECT set_config('app.acting_username', $1, false), "
    "set_config('app.acting_hardware_id', $2, false), "
    "set_config('app.acting_role', $3, false)"
)

_CLEAR_SQL = (
    "SELECT set_config('app.acting_username', '', false), "
    "set_config('app.acting_hardware_id', '', false), "
    "set_config('app.acting_role', '', false)"
)


def set_rls_context(*, username: str = '', hardware_id: str = '', role: str = ''):
    """Set RLS identity for the current async task."""
    _rls_username.set(username)
    _rls_hardware_id.set(hardware_id)
    _rls_role.set(role)


def set_rls_admin():
    """Grant full RLS bypass for background agents / admin operations."""
    set_rls_context(username='SYSTEM', hardware_id='SYSTEM', role='ADMIN')


def clear_rls_context():
    """Clear RLS identity (fail-safe: empty values match no rows)."""
    _rls_username.set('')
    _rls_hardware_id.set('')
    _rls_role.set('')


def get_rls_context() -> dict:
    """Return current RLS context (for debugging)."""
    return {
        'username': _rls_username.get(),
        'hardware_id': _rls_hardware_id.get(),
        'role': _rls_role.get(),
    }


class _RLSAcquireContext:
    """Dual-use object: works as both async context manager and awaitable."""

    __slots__ = ('_pool', '_timeout', '_conn')

    def __init__(self, pool, timeout):
        self._pool = pool
        self._timeout = timeout
        self._conn = None

    async def _acquire_and_set(self):
        kw = {}
        if self._timeout is not None:
            kw['timeout'] = self._timeout
        self._conn = await self._pool.acquire(**kw)
        try:
            await self._conn.execute(
                _SET_SQL,
                _rls_username.get(),
                _rls_hardware_id.get(),
                _rls_role.get(),
            )
        except Exception:
            await self._pool.release(self._conn)
            self._conn = None
            raise
        return self._conn

    def __await__(self):
        return self._acquire_and_set().__await__()

    async def __aenter__(self):
        return await self._acquire_and_set()

    async def __aexit__(self, *exc):
        if self._conn is not None:
            try:
                await self._conn.execute(_CLEAR_SQL)
            except Exception:
                pass
            await self._pool.release(self._conn)
            self._conn = None


class RLSPoolWrapper:
    """Drop-in wrapper for asyncpg.Pool that enforces per-acquire RLS context.

    All attribute access not explicitly defined here falls through to the
    underlying pool via __getattr__.
    """

    __slots__ = ('_pool',)

    def __init__(self, pool):
        object.__setattr__(self, '_pool', pool)

    def acquire(self, *, timeout=None):
        return _RLSAcquireContext(self._pool, timeout)

    async def release(self, conn, *, timeout=None):
        try:
            await conn.execute(_CLEAR_SQL)
        except Exception:
            pass
        kw = {}
        if timeout is not None:
            kw['timeout'] = timeout
        return await self._pool.release(conn, **kw)

    async def execute(self, query, *args, timeout: Optional[float] = None):
        async with self.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def fetch(self, query, *args, timeout: Optional[float] = None):
        async with self.acquire() as conn:
            return await conn.fetch(query, *args, timeout=timeout)

    async def fetchval(self, query, *args, timeout: Optional[float] = None, column: int = 0):
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args, timeout=timeout, column=column)

    async def fetchrow(self, query, *args, timeout: Optional[float] = None):
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args, timeout=timeout)

    def __getattr__(self, name):
        return getattr(self._pool, name)

    def __repr__(self):
        return f'<RLSPoolWrapper wrapping {self._pool!r}>'
