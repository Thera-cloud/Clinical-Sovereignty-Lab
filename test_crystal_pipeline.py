import asyncio
import pytest
import asyncpg
import aioredis
import aiohttp
import json
import os
import sys
import signal
from pathlib import Path
from typing import Dict, Any, List, Optional
import subprocess

from fastapi.testclient import TestClient
from fastapi import FastAPI

# Add backend to path for imports
sys.path.insert(0, 'backend')

from app.main import app as fastapi_app
from app.database import get_db_pool
from app.redis_client import redis_client
from app.websocket.bridge_server import start_bridge_server, stop_bridge_server


class TestCrystalPipeline:
    """Production-grade test suite for Little Nate crystal pipeline."""

    @pytest.fixture(scope='session')
    def event_loop(self):
        """Create async event loop for pytest."""
        loop = asyncio.get_event_loop_policy().new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture(scope='session')
    async def db_pool(self):
        pool = await asyncpg.create_pool(
            dsn=os.getenv('DATABASE_URL', 'postgresql://localhost/little_nate'),
            min_size=1,
            max_size=10,
        )
        yield pool
        await pool.close()

    @pytest.fixture(scope='session')
    async def redis(self):
        redis = await aioredis.from_url('redis://localhost')
        yield redis
        await redis.close()

    @pytest.fixture(scope='session')
    async def test_client(self):
        async with TestClient(fastapi_app) as client:
            yield client

    @classmethod
    def setup_class(cls):
        """Setup before all tests."""
        print("🚀 Starting Crystal Pipeline Tests")

    @classmethod
    def teardown_class(cls):
        """Cleanup after all tests."""
        print("🧹 Cleaning up test artifacts")

    @pytest.mark.asyncio
    async def test_01_cleanup(self, db_pool, redis, request):
        """Clean previous test runs (--clean flag equivalent)."""
        clean = request.config.getoption('--clean')
        if not clean:
            pytest.skip("--clean flag required for cleanup")
        
        async with db_pool.acquire() as conn:
            # Clear test tables
            await conn.execute('''
                DELETE FROM services_state WHERE service_name LIKE 'test_%';
                DELETE FROM websocket_connections WHERE client_id LIKE 'test_%';
                DELETE FROM pipeline_runs WHERE run_id LIKE 'test_%';
            ''')
        
        await redis.flushdb()
        print("✅ Cleanup complete")

    @pytest.mark.asyncio
    async def test_02_database_schema(self, db_pool):
        """Verify database schema is correct."""
        async with db_pool.acquire() as conn:
            # Check critical tables exist
            tables = await conn.fetch('''
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public' 
                AND tablename IN ('services_state', 'websocket_connections', 'pipeline_runs')
            ''')
            assert len(tables) == 3, "Missing required tables"
            
            # Check services table has expected structure
            columns = await conn.fetch('''
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'services_state'
            ''')
            column_names = [row['column_name'] for row in columns]
            required = ['service_name', 'status', 'last_ping', 'metrics']
            for col in required:
                assert col in column_names, f"Missing column: {col}"
        print("✅ Database schema verified")

    @pytest.mark.asyncio
    async def test_03_redis_cache(self, redis):
        """Test Redis cache connectivity and TTL."""
        test_key = "test:cache:ping"
        test_data = {"timestamp": asyncio.get_event_loop().time(), "status": "active"}
        
        await redis.set(test_key, json.dumps(test_data), ex=60)
        cached = await redis.get(test_key)
        assert cached is not None, "Redis set/get failed"
        
        parsed = json.loads(cached)
        assert parsed['status'] == 'active'
        
        # Verify TTL
        ttl = await redis.ttl(test_key)
        assert 50 <= ttl <= 60, f"Unexpected TTL: {ttl}"
        
        await redis.delete(test_key)
        print("✅ Redis cache verified")

    @pytest.mark.asyncio
    async def test_04_websocket_bridge(self):
        """Test WebSocket bridge server startup and basic connectivity."""
        bridge_task = None
        try:
            bridge_task = asyncio.create_task(start_bridge_server())
            await asyncio.sleep(2)  # Give server time to start
            
            # Test WebSocket connection
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect('ws://localhost:8765') as ws:
                    await ws.send_json({"type": "ping", "client_id": "test_client_1"})
                    response = await ws.receive_json()
                    assert response.get('type') == 'pong', "Bridge pong failed"
                    
        finally:
            if bridge_task:
                stop_bridge_server()
                await bridge_task
        print("✅ WebSocket bridge verified")

    @pytest.mark.asyncio
    async def test_05_api_endpoints(self, test_client):
        """Test core FastAPI endpoints."""
        # Health check
        response = test_client.get('/health')
        assert response.status_code == 200
        health_data = response.json()
        assert 'database' in health_data
        assert 'redis' in health_data
        
        # Services endpoint
        response = test_client.get('/services')
        assert response.status_code == 200
        services = response.json()
        assert isinstance(services, list)
        
        print("✅ API endpoints verified")

    @pytest.mark.asyncio
    async def test_06_crystal_pipeline_end_to_end(self, db_pool, redis, test_client):
        """Full crystal pipeline E2E test: ingest → process → serve."""
        
        # 1. Ingest test data
        test_payload = {
            "run_id": "test_crystal_001",
            "services": [
                {"name": "test_service_1", "status": "active", "metrics": {"load": 0.75}},
                {"name": "test_service_2", "status": "idle", "metrics": {"load": 0.12}}
            ],
            "timestamp": asyncio.get_event_loop().time()
        }
        
        # Simulate service registration via API
        response = test_client.post('/services/register', json=test_payload)
        assert response.status_code == 200
        
        # 2. Verify database persistence
        async with db_pool.acquire() as conn:
            records = await conn.fetch(
                "SELECT * FROM services_state WHERE service_name LIKE 'test_%'"
            )
            assert len(records) == 2, "Services not persisted"
            
        # 3. Verify Redis cache
        cached = await redis.get(f"services:test_crystal_001")
        assert cached is not None
        
        # 4. Verify API serves cached data
        response = test_client.get('/services/test_crystal_001')
        assert response.status_code == 200
        assert len(response.json()) == 2
        
        print("✅ Crystal pipeline E2E verified")

    @pytest.mark.asyncio
    async def test_07_error_handling(self, test_client, db_pool):
        """Test error handling and recovery."""
        # Invalid payload
        bad_payload = {"invalid": "data"}
        response = test_client.post('/services/register', json=bad_payload)
        assert response.status_code == 422  # Validation error
        
        # Database rollback test
        async with db_pool.acquire() as conn:
            await conn.execute("BEGIN")
            try:
                await conn.execute("INSERT INTO services_state (service_name) VALUES ('test_invalid')")
                raise Exception("Force rollback")
            except:
                await conn.execute("ROLLBACK")
        
        # Verify no partial data
        records = await conn.fetch("SELECT * FROM services_state WHERE service_name = 'test_invalid'")
        assert len(records) == 0
        
        print("✅ Error handling verified")


async def run_full_suite():
    """Run full test suite programmatically."""
    pytest.main([
        __file__,
        '-v',
        '--clean',
        '-m', 'test'
    ])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test Crystal Pipeline')
    parser.add_argument('--clean', action='store_true', help='Clean previous test data')
    args = parser.parse_args()

    # Handle cleanup signal
    def signal_handler(sig, frame):
        print('\n🛑 Test interrupted, cleaning up...')
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    asyncio.run(run_full_suite())
