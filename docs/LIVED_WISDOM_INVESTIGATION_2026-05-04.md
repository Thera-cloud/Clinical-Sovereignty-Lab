# Lived wisdom × Night School — investigation (2026-05-04)

Per-file: `path` | lines | status | one-line context

---

## 1) `lived_wisdom.py`

- `backend/app/services/lived_wisdom.py` | 1–19 | complete (service spec) | Module doc: pipeline “Session completes → extract_sanctuary_wisdom() … → wisdom_extractions … Night School personalization”.
- `backend/app/services/lived_wisdom.py` | 57–58 | complete | `class LivedWisdomService` — “Extracts and stores therapeutic wisdom from sessions.”
- `backend/app/services/lived_wisdom.py` | 66–77 | **extract API** | `async def extract_sanctuary_wisdom(self, session_id: UUID, family_id: UUID, messages: List[Dict], member_ids: Optional[List[UUID]] = None) -> List[Dict]` — doc: messages `{sender_type, sender_id, text, timestamp}`; returns list of stored entries.
- `backend/app/services/lived_wisdom.py` | 127–163 | complete | `extract_session_wisdom` — 1:1 sessions; Azure then heuristic; `_store_wisdom` with `source="session"`.
- `backend/app/services/lived_wisdom.py` | 167–211 | complete | `get_client_wisdom` / `get_family_wisdom` — read `wisdom_extractions` **`approved = TRUE`** only.
- `backend/app/services/lived_wisdom.py` | 349–377 | complete | `_store_wisdom` INSERT into `wisdom_extractions` — **does not set `approved`** → DB default **FALSE** (migration 015).

**Wire-up target:** call `LivedWisdomService.extract_sanctuary_wisdom(...)` after you have UUIDs + message list in the expected shape.

---

## 2) `bridge_server.py` — `sanctuary_complete` (OPEN_TODOS line drift)

- `docs/OPEN_TODOS.md` cited `~26814` — that region is **`sanctuary_coaching_complete`**, not session completion.
- `backend/app/websocket/bridge_server.py` | 26930–27236 | **partial / no lived-wisdom** | `elif t == "sanctuary_complete":` builds summary via Azure, writes `sanctuary_history/{id}.json`, sends `sanctuary_summary`, `update_client_story`, removes active sanctuary — **no `LivedWisdomService`, no `extract_sanctuary_wisdom`, no import of `lived_wisdom`**.

**Event payload (`d`):** uses `sanctuary_id = d.get('sanctuary_id')`; in-handler data from `sanctuary_engine.data["active_sanctuaries"][sanctuary_id]`: `messages` (items with `sender_name`, `content`), `entry_responses`, `members`, `coaching_sessions`, billing, etc.

**Mismatch risk:** `extract_sanctuary_wisdom` joins on `m.get("text")` and `m.get("sender_id")`; sanctuary messages use **`content`** and **`user_id`-style fields via `sender_name`** in the summary builder (27002–27005). **Not aligned without normalization.**

---

## 3) Existing `lived_wisdom` / classroom references

- `backend/app/main.py` | 370–377 | partial | `LivedWisdomService(db_pool=..., azure_client=...)` → `app.state.lived_wisdom` (**FastAPI backend only**; bridge is a separate process).
- `backend/app/websocket/bridge_server.py` | 19471–19473 | partial | `get_classroom_lived_wisdom_pg` — **coach classroom** string context, not sanctuary.
- `backend/app/services/pg_data_helpers.py` | 871+ | complete | `get_classroom_lived_wisdom_pg` — reads PG for coach UI.
- `backend/app/services/liminal_coaching_engine.py` | 111–376 | partial | Consumes `user_context.get("lived_wisdom")` if provided — **not automatic sanctuary hook**.
- `backend/app/services/insight_accumulator.py` | 585 | partial | Metadata references `"lived_wisdom"` as source_systems.

**Grep `extract_sanctuary_wisdom|sanctuary_wisdom|lived_wisdom` in `backend/app/`:** no `sanctuary_complete` call path; service unused for Family Sanctuary completion in bridge.

---

## 4) Night School ingest paths

- `backend/app/services/night_school/curriculum_pipeline.py` | 40–46 | complete | `ingest_content(self, source_name, content_type, raw_content: str, metadata=None)` — parse → modality → RAG → approval; `_persist_ingestion` → **`night_school_ingestions`**.
- `backend/app/services/night_school_director.py` | 419–560 | complete | **`wisdom.json`** under vault `Admin/night_school` — `add_wisdom_entry`, file-backed cache; **not reading `wisdom_extractions` in grep pass.**

**Conclusion:** Documented “feed Night School” path for lived wisdom is **`wisdom_extractions` + `LivedWisdomService.get_*_wisdom`** (and/or a future bridge to `CurriculumPipeline.ingest_content` / director). **No single function signature** ties `extract_sanctuary_wisdom` output directly into `ingest_content` without new glue.

---

## 5) Schema

- `backend/migrations/015_nate_nudges_wisdom_profiles.sql` | 28–39 | complete | **`wisdom_extractions`**: `user_id`, `family_id`, `session_id` (UUID), `insight_type`, `content`, `effectiveness_score`, `source`, **`approved` BOOL DEFAULT FALSE**, `extracted_at`.
- `backend/migrations/102_classroom_lived_wisdom.sql` | 5–32 | complete | **`classroom_session_analyses`** — coach–client analyses JSONB; separate from sanctuary.
- `backend/migrations/185_night_school_wisdom.sql` | 2–10 | complete | **`night_school_wisdom`**: append-only `entry_id`, `category`, `content`, `source_tag`, …
- `backend/migrations/029_trust_tables.sql` | 7+ | complete | **`night_school_ingestions`** (referenced by `curriculum_pipeline._persist_ingestion`).

---

## 6) Tests

- `backend/tests/test_lived_wisdom.py` | — | present | Unit coverage for service (verify separately if integration hits PG).

---

## Summary (max 3 bullets)

- **Already built:** `LivedWisdomService.extract_sanctuary_wisdom` + `_store_wisdom` → `wisdom_extractions`; FastAPI **`app.state.lived_wisdom`**; Night School file + `CurriculumPipeline` + `night_school_*` tables; classroom lived wisdom PG helper for **coach classroom**, not sanctuary complete.
- **Missing:** `sanctuary_complete` never invokes lived-wisdom extraction; **message key / ID shape** mismatch vs service expectations; **`approved` defaults false** while **`get_*_wisdom` requires TRUE**; no bridge from `wisdom_extractions` into **Night School Director JSON** or **CurriculumPipeline** without new code; **`LivedWisdomService` not on bridge `app.state`** (must construct with bridge `db_pool` or call backend).
- **Estimate for protected `bridge_server.py`:** smallest viable hook (normalize messages, resolve `family_id`/`session_id` as UUIDs, `asyncio.create_task` + try/except around one service call) is **~25–45 lines**; **50-line cap is tight** if UUID resolution, logging, and approval policy are included **in the same file** — helper module recommended for maintainability (outside this investigation).
