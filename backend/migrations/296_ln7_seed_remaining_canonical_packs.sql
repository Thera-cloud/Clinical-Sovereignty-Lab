-- 296_ln7_seed_remaining_canonical_packs.sql
-- QUANTUM-CRYSTAL-ARCH — G2 fix: only 3/18 canonical sandbox CI packs were
-- seeded into ln7_tasks (migration 292). record_outcome() silently drops
-- outcomes for any pack_name without a matching task_id (FK violation
-- swallowed by a bare except), which is why the private-pack canary gate
-- has been stuck at 0/3 usable outcomes despite 18 packs running in the
-- bakeoff. This seeds the remaining 15 canonical packs from
-- backend/app/data/ln_sandbox_ci_packs/packs_index.json so every pack the
-- bakeoff actually runs has a corresponding ln7_tasks row.
-- Additive only.

INSERT INTO ln7_tasks (
    task_id, source, difficulty, task_hash, split, pack_name,
    spdx_license, prompt_summary, metadata_json
)
VALUES
    (
        'pack:load_dotenv_override',
        'authored',
        'medium',
        '38ef11bf1f79250b620b04592b3950231d7095c5c75946f79fb1085b0bff0127',
        'train',
        'load_dotenv_override',
        'FIRST-PARTY',
        'Forbid load_dotenv(override=True). Return a unified diff.',
        '{"pack": "load_dotenv_override", "gold_files": ["broken/config.py"]}'::jsonb
    ),
    (
        'pack:users_no_user_id_column',
        'authored',
        'medium',
        'e8e3b4d4bb179ed44ef3eb8abbfd9eba3963a1b35c734bc5bf3197c6e3167b7f',
        'train',
        'users_no_user_id_column',
        'FIRST-PARTY',
        'Fix users.user_id → username. Return a unified diff.',
        '{"pack": "users_no_user_id_column", "gold_files": ["broken/lookup.py"]}'::jsonb
    ),
    (
        'pack:skyeye_activity_columns',
        'authored',
        'easy',
        'c18bd42a6ddcb6d34efb852bbfbcc3b796ddf235b9cdc953643422d6fae3b77d',
        'train',
        'skyeye_activity_columns',
        'FIRST-PARTY',
        'Fix skyeye_activity column names. Return a unified diff.',
        '{"pack": "skyeye_activity_columns", "gold_files": ["broken/activity.py"]}'::jsonb
    ),
    (
        'pack:require_coach_gate',
        'authored',
        'medium',
        '4b8011124b72cf2f5735525c1d9898b3343cf87fea2289f959b88fbafc4483b5',
        'train',
        'require_coach_gate',
        'FIRST-PARTY',
        'Use require_coach for coach routes. Return a unified diff.',
        '{"pack": "require_coach_gate", "gold_files": ["broken/deps.py"]}'::jsonb
    ),
    (
        'pack:ws_ping_timeout',
        'authored',
        'easy',
        'f0d1495cc4deead594cbb0e8662558a90ae2fbd7543c17fbb16386d5af0ad2ed',
        'train',
        'ws_ping_timeout',
        'FIRST-PARTY',
        'Raise WebSocket ping_timeout to 60. Return a unified diff.',
        '{"pack": "ws_ping_timeout", "gold_files": ["broken/bridge.py"]}'::jsonb
    ),
    (
        'pack:empty_dict_trusted',
        'authored',
        'easy',
        '2c76bf04966d60c3b202d39948802ee05871bdcba109e6d50c467df50e1480fc',
        'train',
        'empty_dict_trusted',
        'FIRST-PARTY',
        'Return [] not {} for empty collections. Return a unified diff.',
        '{"pack": "empty_dict_trusted", "gold_files": ["broken/api.py"]}'::jsonb
    ),
    (
        'pack:expected_role_login',
        'authored',
        'medium',
        '5b8ef2db4d80144650568e7382b843c3f83cbcf0bd7d0391fd250dada11d7ff6',
        'train',
        'expected_role_login',
        'FIRST-PARTY',
        'Pass expected_role on login_request. Return a unified diff.',
        '{"pack": "expected_role_login", "gold_files": ["broken/login.py"]}'::jsonb
    ),
    (
        'pack:jsonb_set_token',
        'authored',
        'medium',
        '1123e5124af7b3bc87e37d5d439d56246a2c4cdab56074a8839bafb16ca9f96e',
        'train',
        'jsonb_set_token',
        'FIRST-PARTY',
        'Use jsonb_set for token usage reset. Return a unified diff.',
        '{"pack": "jsonb_set_token", "gold_files": ["broken/billing.py"]}'::jsonb
    ),
    (
        'pack:redis_environment_prefix',
        'authored',
        'medium',
        '007f54d8433befc03843acb1af33186ba171b3b93d09b91d1b1f4c644a800b6e',
        'train',
        'redis_environment_prefix',
        'FIRST-PARTY',
        'Redis auth key must use ENVIRONMENT. Return a unified diff.',
        '{"pack": "redis_environment_prefix", "gold_files": ["broken/auth_keys.py"]}'::jsonb
    ),
    (
        'pack:auditor_status_codes',
        'authored',
        'easy',
        '75e9c04a3385b5b06d4d13ffcc138c3a7c0de03af3b54465a8f1704e4b4e59c3',
        'train',
        'auditor_status_codes',
        'FIRST-PARTY',
        'Auditor TRUSTED status codes. Return a unified diff.',
        '{"pack": "auditor_status_codes", "gold_files": ["broken/auditor.py"]}'::jsonb
    ),
    (
        'pack:vectorize_outside_db',
        'authored',
        'hard',
        'c34b4b5cc870cfe9deeb091b122eb444777cbf12e24e6c0cd6b3de214b091be5',
        'train',
        'vectorize_outside_db',
        'FIRST-PARTY',
        'Vectorize outside DB acquire block. Return a unified diff.',
        '{"pack": "vectorize_outside_db", "gold_files": ["broken/crystallizer.py"]}'::jsonb
    ),
    (
        'pack:no_iframe_embed',
        'authored',
        'easy',
        'a2f13f90dbe74df7af04eb71b31ce25ed1803891a117594883bf492c8729a657',
        'train',
        'no_iframe_embed',
        'FIRST-PARTY',
        'No iframe embeds for Hive Defense. Return a unified diff.',
        '{"pack": "no_iframe_embed", "gold_files": ["broken/dashboard.py"]}'::jsonb
    ),
    (
        'pack:coach_three_fields',
        'authored',
        'medium',
        '8bb2dd2a60c73dae13377257d86ed6b35afd8081ab3768611a6d05e590ac0dbb',
        'train',
        'coach_three_fields',
        'FIRST-PARTY',
        'Set all three coach assignment fields. Return a unified diff.',
        '{"pack": "coach_three_fields", "gold_files": ["broken/register.py"]}'::jsonb
    ),
    (
        'pack:middleware_not_in_lifespan',
        'authored',
        'hard',
        '4ca385b17f78f32aa802c754077213fe4aeefd0ad1762691a4a324a1f85a9645',
        'train',
        'middleware_not_in_lifespan',
        'FIRST-PARTY',
        'Register middleware at module level. Return a unified diff.',
        '{"pack": "middleware_not_in_lifespan", "gold_files": ["broken/main.py"]}'::jsonb
    ),
    (
        'pack:flutter_nocache_sw',
        'authored',
        'easy',
        '9a7484a621b3b79a9f4137ccb23e5b8d0dc338342d5a91df4039e12a3fcf84e2',
        'train',
        'flutter_nocache_sw',
        'FIRST-PARTY',
        'No-cache flutter_service_worker.js. Return a unified diff.',
        '{"pack": "flutter_nocache_sw", "gold_files": ["broken/nginx.conf"]}'::jsonb
    )
ON CONFLICT (task_id) DO NOTHING;
