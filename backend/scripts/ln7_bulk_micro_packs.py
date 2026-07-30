#!/usr/bin/env python3
"""Generate many compact LN7 CI train packs (broken+test+golden) for data scale.

Used by ln7_seed_train_packs.py. Each entry is a one-line string-return bug→fix.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

from typing import List, Tuple

# (slug, wrong_return, right_return, title_fragment)
# Pack writes broken/fix.py returning the string; test asserts looks_fixed.
_MICRO: List[Tuple[str, str, str, str]] = [
    ("postgres_host_localhost", "POSTGRES_HOST=localhost", "POSTGRES_HOST=postgres", "Docker POSTGRES_HOST"),
    ("redis_host_lan", "REDIS_HOST=10.0.0.81", "REDIS_HOST=redis", "Docker REDIS_HOST"),
    ("load_dotenv_override_true", "load_dotenv(override=True)", "load_dotenv()", "load_dotenv override"),
    ("users_user_id_col", "WHERE user_id = $1", "WHERE username = $1", "users.username lookup"),
    ("skyeye_action_col", "(action, details)", "(type, content)", "skyeye_activity cols"),
    ("require_admin_coach", "require_admin", "require_coach", "coach auth dep"),
    ("ping_timeout_10", "ping_timeout=10", "ping_timeout=60", "WS ping_timeout"),
    ("empty_dict_ok", "return {}", 'return {"status": "ok"}', "empty dict response"),
    ("expected_role_missing", "login_request={}", 'login_request={"expected_role": role}', "expected_role"),
    ("token_balance_overwrite", "EXCLUDED.token_balance", "users.token_balance", "token_balance preserve"),
    ("jsonb_full_replace", "profile_data = $1", "jsonb_set(profile_data", "jsonb_set patch"),
    ("redis_dev_prefix", "nate:development:auth", "nate:production:auth", "ENVIRONMENT prefix"),
    ("auditor_200_only", "code == 200", "code in (200, 400, 404, 422)", "auditor status codes"),
    ("vectorize_in_conn", "await index_wisdom()  # inside acquire", "await index_wisdom()  # after release", "vectorize outside DB"),
    ("iframe_hive", "<iframe src=hive", "<section id=tab-hive", "no iframe embed"),
    ("coach_id_only", '"assigned_coach_id"', '"coach_id" and assigned_coach', "three coach fields"),
    ("middleware_lifespan", "app.add_middleware in lifespan", "app.add_middleware module level", "middleware placement"),
    ("sw_cache_maxage", "max-age=14400", "no-cache, no-store, must-revalidate", "SW no-cache"),
    ("force_recreate_vault", "docker compose --force-recreate", "safe_deploy.sh", "no force-recreate"),
    ("rsync_delete_web", "rsync --delete", "rsync -avz", "no rsync delete"),
    ("compose_no_f", "docker compose up -d", "docker compose -f docker-compose.prod.yml up -d", "compose -f prod"),
    ("bridge_pg_localhost", "POSTGRES_HOST=localhost", "POSTGRES_HOST=postgres", "bridge PG host"),
    ("azure_primary_route", "provider=azure primary", "provider=workers_ai|grok", "sovereign route"),
    ("crystal_source_lt2", "source_count=1", "source_count>=2", "crystal source_count"),
    ("domain_typo", "domain=therapeutics", "domain=clinical", "crystal domain"),
    ("delete_crystal", "DELETE FROM nate_intelligence_crystals", "scope=archived", "archive not delete"),
    ("recall_no_reinforce", "SELECT crystals only", "UPDATE recall_count", "recall reinforcement"),
    ("odpe_invert_ratio", "ratio = icosi/dodec", "ratio = dodec/icosi", "ODPE ratio"),
    ("noise_calls_llm", "NOISE -> call LLM", "NOISE -> skip LLM", "NOISE skip"),
    ("grok_greeting_prompt", "conversation.item.create greeting", "Polly Say only", "no grok greeting"),
    ("nate_speaking_off", "_nate_speaking unused", "_nate_speaking gates mic", "audio gating"),
    ("xtts_in_ladder", "fallback=xtts", "fallback=azure onyx", "voice ladder"),
    ("voice_charge_admin", "charge DrNevedal1", "is_admin_free skip", "admin free voice"),
    ("memory_by_hwid", "WHERE user_id = hardware_id", "WHERE user_id = username", "voice memory id"),
    ("web_before_memory", "web_search first", "memory_query first", "memory priority"),
    ("inject_raw_url", "read URL aloud", "reference topics not URLs", "no raw URLs"),
    ("sentinel_skip_ro", "score all WS types", "_SENTINEL_SKIP read-only", "sentinel skip"),
    ("dual_account_norole", "authenticate without role", "expected_role routing", "dual account role"),
    ("qb_log_token", "log access_token", "get_secure_logger", "QB no token log"),
    ("qb_skip_csrf", "oauth callback no state", "validate CSRF state", "QB CSRF"),
    ("r2_remove_azure", "R2 only no Azure", "R2 then Azure fallback", "R2 fallback"),
    ("heritage_triple", "three backends", "quad R2+Azure+AWS+local", "heritage quad"),
    ("group_by_family_alias", "GROUP BY family_id", "GROUP BY 1", "GROUP BY alias"),
    ("to_jsonb_untyped", "to_jsonb($1)", "to_jsonb($1::int)", "asyncpg cast"),
    ("usage_filter_amount", "amount < 0", "action IN (deduct, usage)", "token usage filter"),
    ("canonical_sources_empty", "return []", "return 4 canonical sources", "usage map sources"),
    ("gkm_tax_id_change", "tax id other", "84-3879515", "GKM tax id"),
    ("share_fee_floor", "fee round down", "ceil tokens/10k * $5", "share fee ceil"),
    ("webauthn_ttl_long", "challenge TTL 600", "challenge TTL 120", "WebAuthn TTL"),
    ("delete_last_yubikey", "allow delete last key", "keep >=1 key", "YubiKey min"),
    ("trust_enforcer_early", "fire minute 5", "fire minute >=10", "enforcer timing"),
    ("auditor_email_direct", "auditor _send_email", "Trust Enforcer only", "no auditor email"),
    ("catch_all_before_health", "/{id} before /health", "/health before /{id}", "route order"),
    ("hive_col_drift", "combined_magnitude", "combined_mag", "hive column names"),
    ("skyeye_platforms_status", "WHERE status=", "query platform_tokens", "observer tokens"),
    ("notification_silent", "except: return []", "logger.warning then []", "observer log"),
    ("family_crystal_hoh", "recall HOH only", "per-member recall", "family recall"),
    ("crystallize_concat", "crystallize conversation blob", "per-message crystallize", "sanctuary crystallize"),
    ("user_recall_thresh_high", "user confidence >= 0.55", "user confidence >= 0.30", "recall threshold"),
    ("ble_full_crystal", "embed full text BLE", "UUID+hash fragment", "BLE fragment"),
    ("defcon_direct", "MeshDefcon.escalate direct", "DistributedDefenseShield", "DEFCON shield"),
    ("canary_reuse", "reuse canary UUID", "unique per device", "canary unique"),
    ("clinical_temp_high", "clinical temperature=0.9", "clinical temperature<=0.3", "temp governance"),
    ("agent_cross_domain", "marketing reads nevedal_metrics", "domain-scoped observe", "agent isolation"),
    ("auto_research_schedule", "research every hour", "research when conf<0.5", "auto-research"),
    ("orange_ollama_public", "0.0.0.0:11434", "10.13.13.5:11434", "Ollama WG bind"),
    ("lb_ws_eq_only", 'eq "/ws"', 'starts_with "/ws"', "LB WS rule"),
    ("clone_bridge", "clone runs bridge", "clone REST only", "no clone bridge"),
    ("ulimit_v_chromium", "ulimit -v for chromium", "MemoryMax only", "no ulimit -v"),
    ("sandbox_python3", 'subprocess "python3"', "sys.executable", "sandbox python"),
    ("vault_chown_skip", "write vault as root 600", "chown 1000:1000", "vault ownership"),
    ("safe_deploy_bypass", "inline docker compose GREEN", "safe_deploy.sh", "safe deploy"),
    ("flutter_to_coach_portal", "rsync coach-portal", "rsync sovereignsanctuary-web", "flutter deploy root"),
    ("cf_purge_skip", "deploy without purge", "cf_purge_flutter_web", "CF purge"),
    ("main_dart_cache", "main.dart.js max-age", "main.dart.js no-cache", "main.dart.js cache"),
    ("index_html_dashboard", "command.html as app index", "flutter bootstrap index", "index protection"),
    ("admin1_recreate", "create admin1", "DrNevedal1 only", "admin identity"),
    ("admin_family_assign", "family_id on DrNevedal1", "no admin family", "admin isolation"),
    ("stripe_voice_merge", "one stripe webhook", "main + voice webhooks", "dual webhook"),
    ("price_prod_id", "STRIPE_PRICE=prod_", "STRIPE_PRICE=price_", "price id format"),
    ("voice_block_main_wh", "credit voice on main webhook", "voice webhook only", "voice credit path"),
    ("ln7_auto_promote_on", "ENABLE_LN7_AUTO_PROMOTE=true", "ENABLE_LN7_AUTO_PROMOTE=false", "LN7 no auto"),
    ("ln7_train_1p5_default", "Qwen2.5-Coder-1.5B", "Qwen2.5-Coder-7B-Instruct", "LN7 fast 7B"),
    ("ln7_promote_vs_32b", "incumbent LN7-baseline for 7B", "incumbent LN7-fast-baseline", "fast incumbent"),
    ("compare_dup_ok", "second compare while lock", "COMPARE_LOCK single-flight", "compare single-flight"),
    ("ab_ok_on_fail", "AB_OK after compare fail", "AB_OK only on success", "AB_OK gate"),
    ("orange_mkdir_store", "mkdir adapters only", "mkdir adapters/REV", "ORANGE mkdir REV"),
    ("keep_after_persist_fail", "KEEP after scp fail", "destroy on persist fail", "persist destroy"),
    ("probe_protect_forever", "protect aged probe.env", "stale probe reaped", "orphan probe"),
    ("thin_force_plist", "FORCE_THIN in LaunchAgent", "FORCE_THIN shell only", "no sticky thin"),
    ("heldout_in_train", "train env_redis_prefix", "heldout excluded", "heldout pack"),
    ("gguf_before_canary", "GGUF before canary wins", "GGUF after 2 canaries", "GGUF gate"),
    ("public_bench_promote", "SWE-bench as promote gate", "private bakeoff promote", "private promote"),
    ("llm_judge_promote", "LLM-as-judge promote", "sandbox CI promote", "no vibe promote"),
    ("best_of_n_hidden", "blend fast/max latency", "publish fast and max rows", "BoN visibility"),
    ("contestant_inside_ln7", "Grok inside LN7 path", "contestants bakeoff only", "LN7 sovereign"),
    ("q4_deep_target", "deep tier q4", "deep tier q5_K_M+", "quant floor"),
    ("major_bump_ln8", "product Little Nate 8", "Little Nate 7 forever", "major fixed"),
    ("revision_as_major", "bump major on train", "timestamp revision only", "revision scheme"),
    ("peft_merge_early", "merge GGUF day-1", "PEFT shadow first", "PEFT first"),
    ("ada_32b_qlora", "32B QLoRA on 20GB Ada", "7B QLoRA on Ada 20GB", "SKU fit"),
    ("min_rows_50_7b", "MIN_ROWS=50 for 7B", "MIN_ROWS=500 for 7B", "7B min rows"),
    ("paraphrase_zero", "PARAPHRASE_N=0", "PARAPHRASE_N>=3", "paraphrase export"),
    ("seed_three_packs", "only 3 micro packs", "seed bulk micro packs", "pack scale"),
    ("mine_no_license", "mine without SPDX check", "PERMISSIVE SPDX only", "mine license"),
    ("export_stubs", "include [patch_hash= stubs", "drop stubs", "clean export"),
    ("db_pool_max_10", "bridge pool max_size=10", "max_size=25", "pool size"),
    ("ping_timeout_regress", "ping_timeout=10 restore", "ping_timeout=60", "ping baseline"),
]


def build_micro_specs() -> list:
    """Return SPECS-compatible tuples for ln7_seed_train_packs."""
    out = []
    for slug, wrong, right, title in _MICRO:
        name = f"micro_{slug}"
        rel = "broken/fix.py"
        broken = (
            f'"""Broken micro-pack: {slug}."""\n\n'
            f"def value() -> str:\n"
            f'    # BUG: {wrong}\n'
            f'    return "{wrong}"\n\n'
            f"def looks_fixed(s: str) -> bool:\n"
            f'    return "{right}" in s and "{wrong}" not in s\n'
        )
        test = (
            "from broken.fix import value, looks_fixed\n\n\n"
            "def test_fixed():\n"
            "    assert looks_fixed(value())\n"
        )
        hunk = [
            "@@ -2,7 +2,7 @@",
            "",
            " def value() -> str:",
            f"-    # BUG: {wrong}",
            f"+    # Fixed: {right}",
            f'-    return "{wrong}"',
            f'+    return "{right}"',
            "",
        ]
        prompt = (
            f"broken/fix.py returns {wrong!r}. Change the return to {right!r} "
            f"and update the BUG comment. Return ONLY a unified diff for broken/fix.py."
        )
        out.append((name, rel, broken, test, hunk, prompt, title))
    return out


if __name__ == "__main__":
    print(len(build_micro_specs()))
