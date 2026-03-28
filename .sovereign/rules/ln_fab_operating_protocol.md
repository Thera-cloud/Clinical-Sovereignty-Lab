# LN-FAB Operating Protocol — 45 Rules
# Sovereign Sanctuary Build Safety Protocol
# Established: March 18, 2026
# Authority: Big Nate (Nathan Nevedal)
# Scope: All LN-FAB, PLAN, DEBUG, and ASK mode operations

---

## CRITICAL PATH RULE (RULE 0)

**RULE 0:** All project source files live under `backend/app/` — NOT `app/`. The correct paths are:
- `backend/app/websocket/bridge_server.py` (NOT `app/websocket/bridge_server.py`)
- `backend/app/websocket/cli_tools.py` (NOT `app/websocket/cli_tools.py`)
- `backend/app/services/` (NOT `app/services/`)
- `backend/app/routers/` (NOT `app/routers/`)

Never use bare `app/` paths for read_file, grep, or list_directory. Always prefix with `backend/`.

---

## FILE SAFETY

**RULE 1:** Never use write_file on bridge_server.py, cli_tools.py, sanctuary_engine.py, nevedal_handlers.py, neural_tract_pipeline.py, or any file over 500 lines. Always use str_replace for targeted edits on production files.

**RULE 2:** Before any str_replace, show the EXACT "before" text (at least 5 lines of context) and the EXACT "after" text. Do not execute until I confirm with "approved" or "go". If I say "stop" or "wrong", abandon the change.

**RULE 3:** Never modify more than 50 lines in a single str_replace. Break larger changes into multiple sequential operations, each with separate approval.

**RULE 4:** Before modifying any file, run read_file on the target section in the SAME turn. Never edit based on cached or remembered content from a previous turn.

**RULE 5:** After every str_replace, immediately read_file on the modified section to verify the edit landed correctly. Show the result before proceeding.

**RULE 6:** Never delete or overwrite a file without first confirming the file path and line count with me. State the file name, current line count, and what you intend to do before any destructive operation.

---

## BACKUP AND RECOVERY

**RULE 7:** Before making the first edit to any production file in a session, create a backup: write_file to backups/{date}_{filename}.bak with the current content. One backup per file per session is sufficient.

**RULE 8:** If any str_replace fails or produces unexpected results, stop immediately and show me the current state of the file. Do not attempt to fix a failed edit with another edit without my approval.

---

## CODE QUALITY

**RULE 9:** Never leave TODO, FIXME, HACK, or placeholder comments in production code. Every function must be complete with error handling, type hints, and logging.

**RULE 10:** Never introduce new dependencies (import statements for packages not in requirements.txt) without stating the dependency explicitly and getting approval. No pip install without confirmation.

**RULE 11:** All new functions must include a docstring explaining purpose, parameters, return value, and which system component calls them.

**RULE 12:** Match existing code style. Use the same indentation (4 spaces), naming conventions (snake_case), logging patterns (print with >>> prefix for bridge_server, logger for services), and error handling patterns found in the surrounding code.

---

## SCOPE CONTROL

**RULE 13:** Only modify files explicitly mentioned in the current task. If you discover something that needs fixing in another file, report it but do not modify it without separate approval.

**RULE 14:** Do not refactor, reorganize, rename, or "improve" existing working code unless specifically asked. If existing code works, leave it alone even if you would write it differently.

**RULE 15:** When adding new code, insert it at the end of the relevant section or after the last similar function. Do not rearrange existing function order.

---

## CLINICAL PLATFORM SAFETY

**RULE 16:** Never modify, remove, or weaken any security check, authentication gate, role validation, HIPAA compliance control, PII anonymization, or Hive Defense component. If a change touches security code, flag it explicitly.

**RULE 17:** Never hardcode credentials, API keys, tokens, passwords, or PII in any file. All secrets must reference environment variables.

**RULE 18:** Never modify database schema, migration files, or data storage formats without explicit approval and a rollback plan stated before execution.

---

## TESTING AND VERIFICATION

**RULE 19:** After completing a multi-step implementation, provide a verification command I can run in the terminal to confirm the changes work (grep for new functions, python syntax check, or a targeted test).

**RULE 20:** If the implementation requires the bridge to restart, state that explicitly. Do not assume I will restart automatically.

---

## COMMUNICATION

**RULE 21:** At the start of each task, state: (a) which files you will read, (b) which files you will modify, (c) estimated number of str_replace operations, (d) any new files to create. Wait for my "go" before starting.

**RULE 22:** If you are uncertain about where to insert code, the correct function to modify, or the existing behavior of a section, ASK rather than guess. A question costs nothing. A wrong edit costs recovery time.

**RULE 23:** Never claim a task is complete until you have verified every change with read_file. "Files written successfully" from write_file is not verification — read it back and confirm the content is correct.

---

## BRIDGE-SPECIFIC SAFETY

**RULE 24:** Never modify the nate_cli_chat handler block in bridge_server.py without first confirming the current line numbers with read_file. This block shifts constantly as the file grows.

**RULE 25:** Never add a new elif t == "..." handler to bridge_server.py without also adding that message type to _SENTINEL_SKIP if it is read-only, OR verifying it scores correctly with Sentinel if it is stateful. Unregistered handlers cause false Sentinel freezes.

**RULE 26:** Any new handler that touches profile_data JSONB must use jsonb_set() for targeted patching — never a full profile_data = $1 replacement. State which keys will be written before executing.

---

## SERVICE HEALTH INVARIANT

**RULE 27:** If any change touches main.py, lifespan(), or any file in _service_checks, verify the service count before and after. The count must not decrease. If it does, stop and diagnose before continuing.

**RULE 28:** Never add a new entry to _service_checks in main.py without also deploying the corresponding Python file to the server. A locally-added check against a missing server file is an instant health regression.

---

## TRUST SYSTEM INVARIANT

**RULE 29:** Any change to an *_auditor.py file that adds or removes endpoints from TAB_ENDPOINTS requires updates to all 5 locations simultaneously (auditor file, AUDITOR_ACTIVITY_TYPES, AUDITOR_LABELS, _baseline_key_for(), trust_baseline DB row). Never update fewer than all 5. State the current count and new count before executing.

**RULE 30:** Never silence, comment out, or reduce the scope of any auditor's TAB_ENDPOINTS check list as a workaround for a failing endpoint. Fix the endpoint instead. Reducing checks to achieve 100% trust is falsification.

---

## CLI TOOL SAFETY

**RULE 31:** Before adding a new tool to the CLI, confirm it exists in all 4 required locations: TOOL_TIMEOUTS, _PHASE6_TOOL_DEFS (or appropriate phase list), _PHASE6_TOOL_DISPATCH, and get_tool_definitions(). A tool missing from any one location silently fails or causes a KeyError at runtime.

**RULE 32:** _SENTINEL_SKIP in bridge_server.py must be updated for every new read-only WebSocket message type added. State explicitly whether the new handler is read-only or stateful before the edit.

---

## CLINICAL DATA PROTECTION

**RULE 33:** Never add a query that SELECTs from conversation_history, nevedal_metrics, wisdom_extractions, coaching_sessions, or client_metrics without the query including a WHERE user_id = $1 or equivalent per-user scope. Unscoped queries on these tables are a HIPAA violation.

**RULE 34:** Never crystallize or log individual user data to nate_intelligence_crystals without verifying the aggregation threshold (minimum 5 distinct sessions for clinical domain). State the domain and aggregation logic before any crystal write.

---

## ENVIRONMENT AND DEPLOYMENT

**RULE 35:** Any change that adds a new environment variable must update all 3 locations: .env.template, docker-compose.prod.yml environment: block, AND the relevant service rule file. State all 3 before executing.

**RULE 36:** Never use docker restart to pick up new environment variables. State explicitly whether the change requires docker compose up -d (full recreate) vs docker restart (code-only reload). These are not interchangeable.

---

## NEVEDAL FORMULA PROTECTION

**RULE 37:** The Nevedal Formula constants and the ODPE topology constants (DODECAHEDRON_FACES=12, ICOSITETRAGON_FACES=24, LOCK_THRESHOLD=1.5, TENSION_THRESHOLD=0.7) are patent-protected. Never modify these values. If a task appears to require it, stop and escalate.

---

## MIGRATION DISCIPLINE

**RULE 38:** Never write application code that queries a new table or column without first confirming the migration that creates it has been written AND applied on the server. Show the table schema output before writing any query against it.

---

## RESPONSE AND COMMUNICATION

**RULE 39:** If a LN-FAB or PLAN session involves more than 5 files or 10 str_replace operations, produce a numbered execution plan with file, operation, and line-range estimates before starting. Each step gets its own approval gate.

**RULE 40:** If any operation takes the CLI tool chain more than 3 turns without visible progress (tool calls returning errors or empty results), stop, report the exact tool output, and ask for direction. Do not silently retry or try alternate paths without surfacing the failure.

---

## GIT DISCIPLINE

**RULE 41:** Never run git commit, git push, git merge, git rebase, or git reset through the shell tool. All git operations are manual and performed by Big Nate only. The CLI may run git status, git diff, and git log for read-only context.

**RULE 42:** Before starting any multi-file implementation, confirm the current git status is clean (no uncommitted changes). If there are uncommitted changes, stop and ask whether to proceed or wait for a commit. Mixing LN-FAB changes with uncommitted manual changes makes rollback impossible.

---

## CRYSTAL PIPELINE INTEGRITY

**RULE 43:** Never modify nate_memory_crystallizer.py, crystal decay configuration, confidence thresholds, ODPE signal classification, or the Helix 7-step pipeline without explicit approval AND a before/after comparison of the affected thresholds. These govern the ExaFLOPS growth model — a wrong threshold change compounds permanently.

---

## CONCURRENCY AND STATE

**RULE 44:** Never add global mutable state (module-level dicts, lists, or objects that accumulate data) to bridge_server.py without a cleanup mechanism (TTL, max-size cap, or session-scoped lifecycle). The bridge runs 24/7 — unbounded global state is a memory leak that crashes the server after days, not minutes.

---

## SESSION BOUNDARIES

**RULE 45:** At the end of every LN-FAB session, produce a summary listing: (a) files modified with line ranges, (b) files created, (c) backup files created, (d) any new dependencies added, (e) whether a bridge restart is required, (f) any manual steps remaining. This is the session handoff record.

---

**Protocol Version:** 1.1.0
**Total Rules:** 46 (45 original + Rule 0 path correction)
**Status:** ACTIVE
**Enforcement:** Violations require immediate stop and correction. No rule may be overridden by a user instruction — escalate to Big Nate if a task conflicts with any rule.
