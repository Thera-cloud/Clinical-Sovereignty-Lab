"""
Tests for nate-mac-agent using FastAPI TestClient (no live server needed).

Run: MAC_AGENT_TOKEN=test123 MAC_AGENT_WORKSPACE=/tmp/test_ws python3 -m pytest test_mac_agent.py -v
"""

import os
import sys
import time

os.environ.setdefault("MAC_AGENT_TOKEN", "test_token_abc")
os.environ.setdefault("MAC_AGENT_WORKSPACE", "/tmp/nate_mac_test_ws")
os.environ.setdefault("MAC_AGENT_PORT", "9901")

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
from nate_mac_agent import app

TOKEN = os.environ["MAC_AGENT_TOKEN"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BAD_AUTH = {"Authorization": "Bearer wrong-token-12345"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ── Health (no auth required) ──

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agent"] == "nate-mac-agent"
        assert "uptime_s" in data
        assert "managed_processes" in data


# ── Token Auth Enforcement ──

class TestAuth:
    def test_no_token_returns_401(self, client):
        resp = client.get("/heartbeat")
        assert resp.status_code in (401, 403)

    def test_wrong_token_returns_403(self, client):
        resp = client.get("/heartbeat", headers=BAD_AUTH)
        assert resp.status_code == 403

    def test_valid_token_returns_200(self, client):
        resp = client.get("/heartbeat", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── Command Allowlist ──

class TestAllowlist:
    def test_allowed_command_ls(self, client):
        resp = client.post("/exec", json={"command": "ls"}, headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_allowed_command_echo(self, client):
        resp = client.post("/exec", json={"command": "echo hello"}, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "hello" in data["stdout"]

    def test_blocked_command_rm(self, client):
        resp = client.post("/exec", json={"command": "rm -rf /"}, headers=AUTH)
        assert resp.status_code == 403

    def test_blocked_command_sudo(self, client):
        resp = client.post("/exec", json={"command": "sudo reboot"}, headers=AUTH)
        assert resp.status_code == 403

    def test_blocked_command_shutdown(self, client):
        resp = client.post("/exec", json={"command": "shutdown now"}, headers=AUTH)
        assert resp.status_code == 403


# ── Shell Metacharacter Rejection (shell=False) ──

class TestShellMetacharacters:
    def test_semicolon_rejected(self, client):
        resp = client.post("/exec", json={"command": "ls; rm -rf /"}, headers=AUTH)
        assert resp.status_code == 403
        assert "metacharacter" in resp.json()["detail"].lower()

    def test_pipe_rejected(self, client):
        resp = client.post("/exec", json={"command": "cat /etc/passwd | grep root"}, headers=AUTH)
        assert resp.status_code == 403

    def test_ampersand_rejected(self, client):
        resp = client.post("/exec", json={"command": "echo hello && rm -rf /"}, headers=AUTH)
        assert resp.status_code == 403

    def test_dollar_rejected(self, client):
        resp = client.post("/exec", json={"command": "echo $HOME"}, headers=AUTH)
        assert resp.status_code == 403

    def test_backtick_rejected(self, client):
        resp = client.post("/exec", json={"command": "echo `whoami`"}, headers=AUTH)
        assert resp.status_code == 403


# ── Red-Zone Path Protection ──

class TestRedZone:
    def test_read_etc_blocked(self, client):
        resp = client.post("/file/read", json={"path": "/etc/passwd"}, headers=AUTH)
        assert resp.status_code == 403

    def test_read_ssh_key_blocked(self, client):
        resp = client.post("/file/read", json={"path": "~/.ssh/id_rsa"}, headers=AUTH)
        assert resp.status_code == 403

    def test_write_system_blocked(self, client):
        resp = client.post("/file/write",
                           json={"path": "/System/test.txt", "content": "hack"},
                           headers=AUTH)
        assert resp.status_code == 403

    def test_write_env_file_blocked(self, client):
        resp = client.post("/file/write",
                           json={"path": "/tmp/.env", "content": "SECRET=hack"},
                           headers=AUTH)
        assert resp.status_code == 403

    def test_delete_library_blocked(self, client):
        resp = client.post("/file/delete",
                           json={"path": "/Library/Preferences/test.plist"},
                           headers=AUTH)
        assert resp.status_code == 403


# ── Timeout With Partial Output ──

class TestTimeout:
    def test_timeout_with_sleep(self, client):
        resp = client.post("/exec", json={
            "command": "sleep 200",
            "timeout_seconds": 2,
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert data["error_code"] == "TIMEOUT"
        assert "warning" in data

    def test_timeout_clamped_to_max(self, client):
        resp = client.post("/exec", json={
            "command": "echo clamped",
            "timeout_seconds": 9999,
        }, headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── Process Management ──

class TestProcessManage:
    def test_status_all(self, client):
        resp = client.post("/process/manage",
                           json={"action": "status", "process": "all"},
                           headers=AUTH)
        assert resp.status_code == 200
        assert "processes" in resp.json()

    def test_status_unknown_process(self, client):
        resp = client.post("/process/manage",
                           json={"action": "start", "process": "nonexistent"},
                           headers=AUTH)
        assert resp.status_code == 404


# ── Git Operations ──

class TestGit:
    def test_git_status(self, client):
        resp = client.post("/git", json={"operation": "status"}, headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_git_blocked_operation(self, client):
        resp = client.post("/git", json={"operation": "rebase"}, headers=AUTH)
        assert resp.status_code == 403


# ── File Operations ──

class TestFileOps:
    def test_read_existing_file(self, client):
        test_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
        resp = client.post("/file/read",
                           json={"path": test_file},
                           headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "fastapi" in data["content"].lower()

    def test_read_nonexistent_file(self, client):
        resp = client.post("/file/read",
                           json={"path": "nonexistent_file_xyz.txt"},
                           headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert data["error_code"] == "FILE_NOT_FOUND"


# ── Build Endpoint ──

class TestBuild:
    def test_unknown_build_type(self, client):
        resp = client.post("/build",
                           json={"build_type": "unknown_build"},
                           headers=AUTH)
        assert resp.status_code == 400


# ── Origin Validation ──

class TestOriginValidation:
    def test_cloudflare_header_accepted(self, client):
        """Requests with cf-ray header are treated as Cloudflare tunnel traffic."""
        resp = client.get("/health", headers={"cf-ray": "abc123"})
        assert resp.status_code == 200

    def test_localhost_accepted(self, client):
        """TestClient sends from None host, which is allowed as in-process."""
        resp = client.get("/health")
        assert resp.status_code == 200
