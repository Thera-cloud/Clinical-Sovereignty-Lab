#!/usr/bin/env python3
"""
Local defense-in-depth proxy for Sovereign IDE (BLUE / Mac).

Bind: 127.0.0.1:8081 → proxies to code-server 127.0.0.1:8080
Requires cookie ss_ide_session (same HMAC as backend / Worker).

Twin Engine should map ide.sovereignsanctuary.net → http://127.0.0.1:8081
(Worker still runs first at CF edge; this stops anyone who reaches the Mac tunnel
without a valid session if Worker is misconfigured).

Env:
  IDE_GATE_SECRET or JWT_SECRET — must match GREEN
  IDE_UPSTREAM — default http://127.0.0.1:8080
  IDE_PROXY_PORT — default 8081
"""

from __future__ import annotations

import http.client
import hashlib
import hmac
import json
import os
import base64
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

COOKIE_NAME = "ss_ide_session"
UPSTREAM = os.environ.get("IDE_UPSTREAM", "http://127.0.0.1:8080")
PORT = int(os.environ.get("IDE_PROXY_PORT", "8081"))
GATEWAY = "https://command.sovereignsanctuary.net/ide.html"


def _secret() -> bytes:
    raw = (os.environ.get("IDE_GATE_SECRET") or os.environ.get("JWT_SECRET") or "").strip()
    if not raw:
        raise SystemExit("Set IDE_GATE_SECRET or JWT_SECRET")
    return hashlib.sha256(f"ide-gate-v1:{raw}".encode("utf-8")).digest()


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def verify(token: str) -> bool:
    if not token or "." not in token:
        return False
    try:
        body, sig = token.rsplit(".", 1)
        expected = _b64url(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return False
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        if payload.get("pur") != "ide":
            return False
        if int(payload.get("exp", 0)) < int(time.time()):
            return False
        return bool(payload.get("sub"))
    except Exception:
        return False


def cookie_token(headers) -> str:
    raw = headers.get("Cookie") or headers.get("cookie") or ""
    for part in raw.split(";"):
        part = part.strip()
        if part.startswith(COOKIE_NAME + "="):
            return part.split("=", 1)[1].strip()
    auth = headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys_stderr = __import__("sys").stderr
        sys_stderr.write("[ide-gate] " + (fmt % args) + "\n")

    def _deny(self):
        body = (
            f'<!DOCTYPE html><html><body style="background:#050505;color:#C9A962;'
            f'font-family:system-ui;text-align:center;padding:4rem">'
            f"<h1>IDE Locked</h1><p>YubiKey session required.</p>"
            f'<p><a style="color:#E8D5A3" href="{GATEWAY}">Open Command IDE gateway</a></p>'
            f"</body></html>"
        ).encode()
        self.send_response(401)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self):
        token = cookie_token(self.headers)
        if not verify(token):
            self._deny()
            return
        up = urlsplit(UPSTREAM)
        conn_cls = http.client.HTTPSConnection if up.scheme == "https" else http.client.HTTPConnection
        host = up.hostname or "127.0.0.1"
        port = up.port or (443 if up.scheme == "https" else 80)
        path = self.path
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")}
        headers["Host"] = f"{host}:{port}" if port not in (80, 443) else host
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        conn = conn_cls(host, port, timeout=120)
        try:
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() in ("transfer-encoding", "connection"):
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            conn.close()

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_OPTIONS(self):
        self._proxy()

    def do_HEAD(self):
        self._proxy()


def main():
    _secret()  # fail fast
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[ide-gate] listening 127.0.0.1:{PORT} → {UPSTREAM}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
