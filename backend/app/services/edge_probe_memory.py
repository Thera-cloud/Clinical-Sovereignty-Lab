"""Remember edge wordlist probes and answer a patterned source with a canary page.

The page is the inbound mirror. This module does not ban, scan, or open a connection
back to the source.
"""

from __future__ import annotations

import json
import os
from typing import Optional
from uuid import uuid4

_TOKEN_PATH = os.environ.get("EDGE_PROBE_TOKEN_FILE", "/app/data/edge_probe_ingest_token")


def ingest_token() -> str:
    env = os.environ.get("EDGE_PROBE_INGEST_TOKEN", "").strip()
    if env:
        return env
    try:
        with open(_TOKEN_PATH, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def enabled() -> bool:
    return os.environ.get("ENABLE_EDGE_PROBE_MEMORY", "true").lower() not in ("0", "false", "off")


def path_class(uri: str) -> str:
    path = (uri or "/").split("?", 1)[0].lower()[:180]
    if path.startswith("/.ec/"):
        return "canary"
    if ".git" in path:
        return "git"
    if path.endswith((".php", ".phtml", ".phar")):
        return "php"
    if any(part in path for part in ("wp-admin", "wp-login", "wp-config", "wp-content", "wp-includes", "xmlrpc", "phpunit", "cgi-bin")):
        return "wordpress"
    if ".env" in path or path.startswith("/."):
        return "env"
    return "other"


def canary_from_path(uri: str) -> str:
    path = (uri or "").split("?", 1)[0]
    marker = "/.ec/"
    if marker not in path:
        return ""
    return path.split(marker, 1)[1].strip("/")[:80]


def pattern_ready(hit_count: int, class_count: int) -> bool:
    return hit_count >= 6 or class_count >= 3


def mirror_page(canary_id: str) -> str:
    return f"<!doctype html><title></title>\n<!-- ec:{canary_id} -->\n"


async def remember(pool, source_ip: str, host: str, uri: str, hive: Optional[dict] = None) -> dict:
    """Store the hit. Issue the canary once the source shows a wordlist pattern."""
    kind = path_class(uri)
    token = canary_from_path(uri)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO edge_probe_events (source_ip, host, path_class) VALUES ($1, $2, $3)",
                source_ip,
                (host or "")[:80],
                kind,
            )
            if kind == "canary" and token:
                await conn.execute(
                    """UPDATE edge_probe_sources
                          SET canary_seen_at = now(), last_seen = now()
                        WHERE source_ip = $1 AND canary_id = $2""",
                    source_ip,
                    token,
                )
            row = await conn.fetchrow(
                """INSERT INTO edge_probe_sources (source_ip, hit_count, classes, class_count)
                   VALUES ($1, 1, to_jsonb(ARRAY[$2]::text[]), 1)
                   ON CONFLICT (source_ip) DO UPDATE SET
                     hit_count = edge_probe_sources.hit_count + 1,
                     classes = (
                       SELECT COALESCE(jsonb_agg(DISTINCT c), '[]'::jsonb)
                         FROM (
                           SELECT jsonb_array_elements_text(edge_probe_sources.classes) AS c
                           UNION SELECT $2
                         ) s
                     ),
                     class_count = (
                       SELECT count(DISTINCT c)::int
                         FROM (
                           SELECT jsonb_array_elements_text(edge_probe_sources.classes) AS c
                           UNION SELECT $2
                         ) s
                     ),
                     last_seen = now()
                   RETURNING hit_count, class_count, mirror_issued, canary_id, namespace_id""",
                source_ip,
                kind,
            )
            issued = bool(row["mirror_issued"])
            canary_id = row["canary_id"] or ""
            namespace_id = row["namespace_id"] or ""
            if (not issued) and pattern_ready(row["hit_count"], row["class_count"]):
                canary_id = str(uuid4())
                namespace_id = await _open_namespace(hive, source_ip, kind)
                await conn.execute(
                    """UPDATE edge_probe_sources
                          SET mirror_issued = true,
                              pattern = 'wordlist',
                              canary_id = $2,
                              namespace_id = $3
                        WHERE source_ip = $1""",
                    source_ip,
                    canary_id,
                    namespace_id,
                )
                await conn.execute(
                    """INSERT INTO skyeye_activity (type, content, platform, created_at)
                       VALUES ('edge_probe_pattern', $1, 'edge', now())""",
                    json.dumps({
                        "pattern": "wordlist",
                        "source": source_ip,
                        "hits": row["hit_count"],
                        "classes": row["class_count"],
                        "namespace_id": namespace_id,
                    }),
                )
                issued = True
    _note_fibre(hive, source_ip, kind)
    return {"mirror": issued, "canary_id": canary_id, "path_class": kind}


async def _open_namespace(hive: Optional[dict], source_ip: str, kind: str) -> str:
    shell = (hive or {}).get("mirror_shell")
    manager = getattr(shell, "_namespace_mgr", None)
    if manager is None:
        return ""
    try:
        namespace = await manager.create_namespace(source_ip, {"path_class": kind, "pattern": "wordlist"})
        return str(namespace.namespace_id)
    except Exception:
        return ""


def _note_fibre(hive: Optional[dict], source_ip: str, kind: str) -> None:
    curiosity = (hive or {}).get("curiosity_protocol")
    observe = getattr(curiosity, "observe", None)
    if observe is None:
        return
    try:
        observe("edge", source_ip, kind)
    except Exception:
        return
