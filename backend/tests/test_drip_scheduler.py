"""
Tests for DripScheduler — background job scheduler.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from app.services.drip_scheduler import DripScheduler


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestDripSchedulerInit:
    @patch("app.services.drip_scheduler.AsyncIOScheduler")
    def test_initialization_creates_scheduler(self, mock_scheduler_cls, fake_pool):
        """DripScheduler should create an AsyncIOScheduler instance."""
        mock_scheduler_cls.return_value = MagicMock()

        scheduler = DripScheduler(db_pool=fake_pool)

        assert scheduler.db_pool is fake_pool
        assert scheduler.scheduler is not None
        mock_scheduler_cls.assert_called_once()


class TestDripSchedulerStart:
    @patch("app.services.drip_scheduler.AsyncIOScheduler")
    def test_start_registers_expected_jobs(self, mock_scheduler_cls, fake_pool):
        """start() should register 8 scheduled jobs."""
        mock_scheduler = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler

        scheduler = DripScheduler(db_pool=fake_pool)
        scheduler.start()

        # Should have called add_job 8 times (per source: prints "8 jobs")
        assert mock_scheduler.add_job.call_count == 8
        mock_scheduler.start.assert_called_once()

        # Verify job IDs that were registered
        job_ids = [
            call.kwargs.get("id") or call[1].get("id", "")
            for call in mock_scheduler.add_job.call_args_list
        ]
        # Flatten — add_job is called with keyword args
        registered_ids = set()
        for call in mock_scheduler.add_job.call_args_list:
            _, kwargs = call
            if "id" in kwargs:
                registered_ids.add(kwargs["id"])

        expected_ids = {
            "check_pending_drips",
            "check_sms_fallbacks",
            "check_ticket_reminders",
            "check_expired_tickets",
            "update_analytics",
            "check_approval_auto_exec",
            "run_foresight_engine",
            "run_coherence_pulse",
        }
        assert registered_ids == expected_ids


class TestTrialUserUuidResolution:
    @pytest.mark.asyncio
    async def test_resolve_from_profile_cache(self, fake_pool):
        uid = UUID("faacaf2e-4ef0-4750-926c-3dc65ccfbf62")
        scheduler = DripScheduler(db_pool=fake_pool)
        profile = {"user_uuid": str(uid), "hardware_id": "CLIENT_MBRYCE_ID"}
        got = await scheduler._resolve_user_uuid(profile, "client_Mbryce")
        assert got == uid
        fake_pool.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_from_db_by_hardware_id(self, fake_pool):
        uid = UUID("faacaf2e-4ef0-4750-926c-3dc65ccfbf62")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": uid})
        fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        scheduler = DripScheduler(db_pool=fake_pool)
        profile = {"hardware_id": "CLIENT_MBRYCE_ID", "username": "Mbryce"}
        got = await scheduler._resolve_user_uuid(profile, "client_Mbryce")
        assert got == uid
        assert profile["user_uuid"] == str(uid)
