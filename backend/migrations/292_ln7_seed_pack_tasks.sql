-- 292_ln7_seed_pack_tasks.sql
-- QUANTUM-CRYSTAL-ARCH — seed first-party sandbox packs as train/heldout tasks
-- Additive only.

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, pack_name, prompt_summary, metadata_json)
VALUES
    (
        'pack:asyncpg_cast',
        'authored',
        'easy',
        encode(sha256('pack:asyncpg_cast:v1'::bytea), 'hex'),
        'train',
        'asyncpg_cast',
        'Fix asyncpg polymorphic cast failures. Return a unified diff.',
        '{"pack":"asyncpg_cast","gold_files":["app.py"]}'::jsonb
    ),
    (
        'pack:catch_all_routes',
        'authored',
        'medium',
        encode(sha256('pack:catch_all_routes:v1'::bytea), 'hex'),
        'train',
        'catch_all_routes',
        'Fix FastAPI catch-all route ordering. Return a unified diff.',
        '{"pack":"catch_all_routes","gold_files":["routes.py"]}'::jsonb
    ),
    (
        'pack:env_redis_prefix',
        'authored',
        'medium',
        encode(sha256('pack:env_redis_prefix:v1'::bytea), 'hex'),
        'heldout',
        'env_redis_prefix',
        'Fix ENVIRONMENT Redis key prefix mismatch. Return a unified diff.',
        '{"pack":"env_redis_prefix","gold_files":["redis_keys.py"]}'::jsonb
    )
ON CONFLICT (task_id) DO NOTHING;
