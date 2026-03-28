"""
LITTLE NATE — Vectorize Pipeline Trust Auditor
Verifies both PUSH (embedding + upsert) and RETRIEVAL (query + recall)
across all 6 Vectorize indexes plus Workers AI embedding health.

12 checks across 4 tabs:
  Tab 1: Embedding Health (2 checks — Workers AI reachability + dimension validation)
  Tab 2: Push Pipeline (3 checks — end-to-end upsert probe, cleanup, latency)
  Tab 3: Retrieval Quality (6 checks — one per Vectorize index reachability)
  Tab 4: Data Integrity (1 check — metadata schema validation on recalled vectors)

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 65s.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.vectorize_pipeline_auditor")

AUDIT_HOURS = {5, 17, 23}

TAB_ENDPOINTS = [
    {
        "tab": "Embedding Health",
        "tab_num": 1,
        "endpoints": [
            ("PROBE", "workers_ai_reachable"),
            ("PROBE", "embedding_dimension_384"),
        ],
    },
    {
        "tab": "Push Pipeline",
        "tab_num": 2,
        "endpoints": [
            ("PROBE", "push_embed_ok"),
            ("PROBE", "push_upsert_ok"),
            ("PROBE", "push_recall_ok"),
        ],
    },
    {
        "tab": "Retrieval Quality",
        "tab_num": 3,
        "endpoints": [
            ("PROBE", "index_conversation_reachable"),
            ("PROBE", "index_vault_reachable"),
            ("PROBE", "index_wisdom_reachable"),
            ("PROBE", "index_me2me_reachable"),
            ("PROBE", "index_sessions_reachable"),
            ("PROBE", "index_annotations_reachable"),
        ],
    },
    {
        "tab": "Data Integrity",
        "tab_num": 4,
        "endpoints": [
            ("PROBE", "metadata_schema_valid"),
        ],
    },
]


class VectorizePipelineAuditor:

    def __init__(self, db_pool, notification_system=None, auth_token: str = "",
                 app_state=None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._auth_token = auth_token
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("VectorizePipelineAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("VectorizePipelineAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(65)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if now.hour in AUDIT_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows
                        if k.startswith(now.date().isoformat())
                    }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("VectorizePipelineAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all()

        # Email silenced — Trust Enforcer sends consolidated report

        total = sum(t["total"] for t in results)
        trusted = sum(t["trusted"] for t in results)

        detail_json = json.dumps({
            "trusted": trusted,
            "total": total,
            "tabs": [
                {
                    "tab": t["tab"],
                    "trusted": t["trusted"],
                    "total": t["total"],
                    "checks": t["endpoints"],
                }
                for t in results
            ],
        })

        await self._log_activity(
            "system", "vectorize_pipeline_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}",
            "success",
        )
        logger.info("VectorizePipelineAuditor: scorecard — %d/%d TRUSTED", trusted, total)

    async def _audit_all(self) -> list:
        from app.services.vectorize_service import (
            is_vectorize_configured, generate_embeddings, verify_push_pipeline,
            verify_retrieval_quality, INDEX_NAMES,
        )

        results = []

        if not is_vectorize_configured():
            for tab_def in TAB_ENDPOINTS:
                tab_result = {
                    "tab": tab_def["tab"], "tab_num": tab_def["tab_num"],
                    "total": len(tab_def["endpoints"]), "trusted": 0,
                    "warning": len(tab_def["endpoints"]), "failed": 0,
                    "endpoints": [
                        {"method": "PROBE", "path": ep[1], "code": 0,
                         "ms": 0, "status": "WARNING",
                         "detail": "Vectorize not configured (CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN missing)"}
                        for ep in tab_def["endpoints"]
                    ],
                }
                results.append(tab_result)
            return results

        # --- Tab 1: Embedding Health ---
        tab1 = {
            "tab": "Embedding Health", "tab_num": 1,
            "total": 2, "trusted": 0, "warning": 0, "failed": 0,
            "endpoints": [],
        }

        t0 = time.monotonic()
        test_emb = await generate_embeddings(["Vectorize pipeline auditor health check"])
        embed_ms = int((time.monotonic() - t0) * 1000)

        if test_emb and len(test_emb) == 1:
            tab1["endpoints"].append({
                "method": "PROBE", "path": "workers_ai_reachable",
                "code": 200, "ms": embed_ms, "status": "TRUSTED",
                "detail": f"Workers AI responded in {embed_ms}ms",
            })
            tab1["trusted"] += 1

            dim = len(test_emb[0])
            if dim == 384:
                tab1["endpoints"].append({
                    "method": "PROBE", "path": "embedding_dimension_384",
                    "code": 200, "ms": 0, "status": "TRUSTED",
                    "detail": f"Embedding dimension = {dim} (expected 384)",
                })
                tab1["trusted"] += 1
            else:
                tab1["endpoints"].append({
                    "method": "PROBE", "path": "embedding_dimension_384",
                    "code": 0, "ms": 0, "status": "WARNING",
                    "detail": f"Unexpected dimension {dim} (expected 384)",
                })
                tab1["warning"] += 1
        else:
            tab1["endpoints"].append({
                "method": "PROBE", "path": "workers_ai_reachable",
                "code": 0, "ms": embed_ms, "status": "FAILED",
                "detail": f"Workers AI embedding failed or returned None ({embed_ms}ms)",
            })
            tab1["failed"] += 1
            tab1["endpoints"].append({
                "method": "PROBE", "path": "embedding_dimension_384",
                "code": 0, "ms": 0, "status": "FAILED",
                "detail": "Cannot check dimension — embedding failed",
            })
            tab1["failed"] += 1

        results.append(tab1)

        # --- Tab 2: Push Pipeline (end-to-end) ---
        tab2 = {
            "tab": "Push Pipeline", "tab_num": 2,
            "total": 3, "trusted": 0, "warning": 0, "failed": 0,
            "endpoints": [],
        }

        push_result = await verify_push_pipeline(user_id="audit_client")

        if push_result.get("embed_ok"):
            tab2["endpoints"].append({
                "method": "PROBE", "path": "push_embed_ok",
                "code": 200, "ms": push_result.get("embed_ms", 0),
                "status": "TRUSTED",
                "detail": f"Probe embedding generated in {push_result.get('embed_ms', 0)}ms",
            })
            tab2["trusted"] += 1
        else:
            tab2["endpoints"].append({
                "method": "PROBE", "path": "push_embed_ok",
                "code": 0, "ms": push_result.get("embed_ms", 0),
                "status": "FAILED",
                "detail": f"Probe embedding failed: {push_result.get('error', 'unknown')}",
            })
            tab2["failed"] += 1

        if push_result.get("upsert_ok"):
            tab2["endpoints"].append({
                "method": "PROBE", "path": "push_upsert_ok",
                "code": 200, "ms": push_result.get("upsert_ms", 0),
                "status": "TRUSTED",
                "detail": f"Upserted probe vector in {push_result.get('upsert_ms', 0)}ms",
            })
            tab2["trusted"] += 1
        else:
            tab2["endpoints"].append({
                "method": "PROBE", "path": "push_upsert_ok",
                "code": 0, "ms": push_result.get("upsert_ms", 0),
                "status": "FAILED" if push_result.get("embed_ok") else "WARNING",
                "detail": "Upsert failed (upstream embed may have failed)",
            })
            tab2["failed" if push_result.get("embed_ok") else "warning"] += 1

        if push_result.get("recall_ok"):
            tab2["endpoints"].append({
                "method": "PROBE", "path": "push_recall_ok",
                "code": 200, "ms": push_result.get("query_ms", 0),
                "status": "TRUSTED",
                "detail": f"Recalled probe vector in {push_result.get('query_ms', 0)}ms",
            })
            tab2["trusted"] += 1
        elif push_result.get("query_ok") and not push_result.get("recall_ok"):
            tab2["endpoints"].append({
                "method": "PROBE", "path": "push_recall_ok",
                "code": 0, "ms": push_result.get("query_ms", 0),
                "status": "WARNING",
                "detail": "Query succeeded but probe vector not in top-5 (index propagation delay)",
            })
            tab2["warning"] += 1
        else:
            tab2["endpoints"].append({
                "method": "PROBE", "path": "push_recall_ok",
                "code": 0, "ms": push_result.get("query_ms", 0),
                "status": "FAILED" if push_result.get("upsert_ok") else "WARNING",
                "detail": "Query failed (upstream upsert may have failed)",
            })
            s = "failed" if push_result.get("upsert_ok") else "warning"
            tab2[s] += 1

        results.append(tab2)

        # --- Tab 3: Retrieval Quality (one per index) ---
        tab3 = {
            "tab": "Retrieval Quality", "tab_num": 3,
            "total": 6, "trusted": 0, "warning": 0, "failed": 0,
            "endpoints": [],
        }

        retrieval_results = await verify_retrieval_quality(user_id="audit_client")

        index_to_check = {
            "conversation": "index_conversation_reachable",
            "vault": "index_vault_reachable",
            "wisdom": "index_wisdom_reachable",
            "me2me": "index_me2me_reachable",
            "session": "index_sessions_reachable",
            "annotation": "index_annotations_reachable",
        }

        for source, check_name in index_to_check.items():
            r = retrieval_results.get(source, {})
            if r.get("reachable"):
                tab3["endpoints"].append({
                    "method": "PROBE", "path": check_name,
                    "code": 200, "ms": 0, "status": "TRUSTED",
                    "detail": (
                        f"{r.get('index', source)}: {r.get('match_count', 0)} matches, "
                        f"top_score={r.get('top_score', 0)}, metadata_valid={r.get('metadata_valid', 'n/a')}"
                    ),
                })
                tab3["trusted"] += 1
            else:
                tab3["endpoints"].append({
                    "method": "PROBE", "path": check_name,
                    "code": 0, "ms": 0, "status": "FAILED",
                    "detail": f"{r.get('index', source)}: {r.get('error', 'unreachable')}",
                })
                tab3["failed"] += 1

        results.append(tab3)

        # --- Tab 4: Data Integrity (metadata schema) ---
        tab4 = {
            "tab": "Data Integrity", "tab_num": 4,
            "total": 1, "trusted": 0, "warning": 0, "failed": 0,
            "endpoints": [],
        }

        all_metadata_valid = all(
            r.get("metadata_valid", True)
            for r in retrieval_results.values()
            if r.get("reachable") and r.get("match_count", 0) > 0
        )

        if all_metadata_valid:
            tab4["endpoints"].append({
                "method": "PROBE", "path": "metadata_schema_valid",
                "code": 200, "ms": 0, "status": "TRUSTED",
                "detail": "All recalled vectors have valid user_id metadata",
            })
            tab4["trusted"] += 1
        else:
            invalid_indexes = [
                s for s, r in retrieval_results.items()
                if r.get("reachable") and r.get("match_count", 0) > 0
                and not r.get("metadata_valid", True)
            ]
            tab4["endpoints"].append({
                "method": "PROBE", "path": "metadata_schema_valid",
                "code": 0, "ms": 0, "status": "WARNING",
                "detail": f"Missing user_id in metadata for: {', '.join(invalid_indexes)}",
            })
            tab4["warning"] += 1

        results.append(tab4)

        return results

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, severity: str = "info"):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                """, platform, activity_type, content, severity)
        except Exception:
            pass
