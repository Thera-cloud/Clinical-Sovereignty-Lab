STATUS: HYPOTHESES ONLY — n=12. Re-test at fuel-era n>=50 before any
training-data curation or recipe decision (incl. r16-beat-r32 observation).

# Attempt 6 Delta Autopsy

Arm A: `LN7-2026-07-30T190327Z`  
Arm B: `LN7-2026-07-30T191329Z`

## Per-task (heuristic tags — not training labels)

### `asyncpg_cast`

- ARM A passed=False score=0.25 tag=`wrong_logic`
- ARM B passed=False score=0.0 tag=`wrong_logic`

<details><summary>Arm A raw_text</summary>

```diff
--- a/broken/handler.py	2026-07-28 00:00:00
+++ b/broken/handler.py	2026-07-28 00:00:00
@@ -3,7 +3,7 @@

 def build_token_balance_sql() -> str:
     # BUG: asyncpg cannot infer polymorphic type for to_jsonb($1)
-    return (
+    return (
         "UPDATE users SET profile_data = jsonb_set("
         "profile_data, '{token_balance}', to_jsonb($1))"
-    )
+    )

 def looks_fixed(sql: str) -> bool:
     """Judge helper used by pack tests (not production code)."""
     s = sql.lower().replace(" ", "")
     return "to_jsonb($1::int)" in s or "to_jsonb(($1)::int)" in s
```

</details>

<details><summary>Arm B raw_text</summary>

```diff
--- a/broken/handler.py	2026-07-28 00:00:00
+++ b/broken/handler.py	2026-07-28 00:00:00
@@ -2,10 +2,10 @@
 
 
 def build_token_balance_sql() -> str:
-    # BUG: asyncpg cannot infer polymorphic type for to_jsonb($1)
+    # Fixed: explicit cast for asyncpg polymorphic to_jsonb
     return (
         "UPDATE users SET profile_data = jsonb_set("
-        "profile_data, '{token_balance}', to_jsonb($1))"
+        "profile_data, '{token_balance}', to_jsonb($1::int))"
     )
 
 

This diff patches the listed files. The hunk below shows the changed lines. The file broken/handler.py had a BUG comment indicating that asyncpg could not infer the polymorphic type for to_jsonb($1). The fix involved changing the SQL fragment to_jsonb($1) into to_jsonb($1::int) inside the return string. Additionally, the BUG comment was updated to reflect the change. No prose markdown fences are used.
```

</details>

### `catch_all_routes`

- ARM A passed=False score=0.25 tag=`wrong_logic`
- ARM B passed=False score=0.0 tag=`wrong_logic`

<details><summary>Arm A raw_text</summary>

```diff
--- a/broken/routes.py	2026-07-14 00:00:00
+++ b/broken/routes.py	2026-07-14 00:00:00
@@ -1,5 +1,5 @@
 """Broken on purpose — catch-all swallows /health."""
 
-ROUTE_ORDER = [
+ROUTE_ORDER = [
     ("GET", "/{assessment_id}"),  # catch-all first — BUG
     ("GET", "/health"),
 ]
@@ -8,7 +8,7 @@ def health_is_before_catch_all(order=Non
 
 def health_is_before_catch_all(order=None) -> bool:
     order = order if order is not None else ROUTE_ORDER
-    paths = [p for _, p in order]
+    paths = [p for m, p in order]
     try:
         return paths.index("/health") < paths.index("/{assessment_id}")
     except ValueError:
```

</details>

<details><summary>Arm B raw_text</summary>

```diff
--- a/broken/routes.py	2026-07-28 00:00:00
+++ b/broken/routes.py	2026-07-28 00:00:00
@@ -1,8 +1,8 @@
 """Broken on purpose — catch-all swallows /health."""
 
 ROUTE_ORDER = [
-    ("GET", "/{assessment_id}"),  # catch-all first — BUG
     ("GET", "/health"),
+    ("GET", "/{assessment_id}"),
 ]
 
 

Return type hinting is not enforced, so the function will still run after your change. The BUG comment should also be updated.
```

</details>

### `env_redis_prefix`

- ARM A passed=False score=0.25 tag=`wrong_logic`
- ARM B passed=False score=0.0 tag=`wrong_logic`

<details><summary>Arm A raw_text</summary>

```diff
--- a/broken/auth_keys.py	2026-07-14 00:00:00
+++ b/broken/auth_keys.py	2026-07-14 00:00:00
@@ -5,7 +5,7 @@
 # BUG: local-dev default leaks into Docker "production" containers
 DEFAULT_ENVIRONMENT = "development"

-def redis_auth_key(token: str, environment: Optional[str] = None) -> str:
+def redis_auth_key(token: str, environment: Optional[str] = None) -> str:
     env = environment or DEFAULT_ENVIRONMENT
     return f"nate:{env}:auth:{token}"

-def production_ready() -> bool:
+def production_ready() -> bool:
     return DEFAULT_ENVIRONMENT == "production"
```

</details>

<details><summary>Arm B raw_text</summary>

```diff
--- a/broken/auth_keys.py	2026-07-28 00:00:00
+++ b/broken/auth_keys.py	2026-07-28 00:00:00
@@ -1,6 +1,6 @@
 """Broken on purpose — ENVIRONMENT mismatch breaks REST auth."""
 from typing import Optional

-# BUG: local-dev default leaks into Docker "production" containers
+FIXED_DEFAULT = "production"

-def redis_auth_key(token: str, environment: Optional[str] = None) -> str:
+def redis_auth_key(token: str, environment: Optional[str] = None) -> str:
     env = environment or FIXED_DEFAULT
     return f"nate:{env}:auth:{token}"

 def production_ready() -> bool:
-    return DEFAULT_ENVIRONMENT == "production"
+    return FIXED_DEFAULT == "production"

Return ONLY a unified diff that patches the listed files. No prose, no markdown fences. Hunk context lines must match the FILE bodies above exactly (same indentation and quotes).

--- a/broken/auth_keys.py	2026-07-28 00:00:00
+++ b/broken/auth_keys.py	2026-07-28 00:00:00
@@ -1,6 +1,6 @@
 """Broken on purpose — ENVIRONMENT mismatch breaks REST auth."""
 from typing import Optional

-# BUG: local-dev default leaks into Docker "production" containers
+FIXED_DEFAULT = "production"

-def redis_auth_key(token: str, environment: Optional[str] = None) -> str:
+def redis_auth_key(token: str, environment: Optional[str] = None) -> str:
     env = environment or FIXED_DEFAULT
     return f"nate:{env}:auth:{token}"

 def production_ready() -> bool:
-    return DEFAULT_ENVIRONMENT == "production"
+    return FIXED_DEFAULT == "production"

Return ONLY a unified diff that patches the listed files. No prose, no markdown fences. Hunk context lines must match the FILE bodies above exactly (same indentation and quotes).
```

</details>

### `load_dotenv_override`

- ARM A passed=False score=0.0 tag=`wrong_logic`
- ARM B passed=True score=1.0 tag=`ok_pass`

<details><summary>Arm A raw_text</summary>

```diff
--- a/broken/config.py	2026-07-14 00:00:00
+++ b/broken/config.py	2026-07-14 00:00:00
@@ -3,7 +3,7 @@

 def load_settings_call() -> str:
-    # BUG: override=True wipes REDIS_HOST from compose
+    # Fixed: no override allows Docker env to prevail
-    return "load_dotenv(override=True)"
+    return "load_dotenv()"

 def looks_fixed(s: str) -> bool:
     return "override=True" not in s.replace(" ", "") and "load_dotenv" in s
```

</details>

<details><summary>Arm B raw_text</summary>

```diff
--- a/broken/config.py	2026-07-28 00:00:00
+++ b/broken/config.py	2026-07-28 00:00:00
@@ -2,7 +2,7 @@

 def load_settings_call() -> str:
-    # BUG: override=True wipes REDIS_HOST from compose
+    # Fixed: never clobber Docker-injected env
-    return "load_dotenv(override=True)"
+    return "load_dotenv()"

 def looks_fixed(s: str) -> bool:
     return "override=True" not in s.replace(" ", "") and "load_dotenv" in s

Return ONLY a unified diff that patches the listed files. No prose, no markdown fences. Hunk context lines must match the FILE bodies above exactly (same indentation and quotes).

--- a/broken/config.py	2026-07-28 00:00:00
+++ b/broken/config.py	2026-07-28 00:00:00
@@ -2,7 +2,7 @@

 def load_settings_call() -> str:
-    # BUG: override=True wipes REDIS_HOST from compose
+    # Fixed: never clobber Docker-injected env
-    return "load_dotenv(override=True)"
+    return "load_dotenv()"

 def looks_fixed(s: str) -> bool:
     return "override=True" not in s.replace(" ", "") and "load_dotenv" in s
```

</details>

### `skyeye_activity_columns`

- ARM A passed=True score=1.0 tag=`ok_pass`
- ARM B passed=False score=0.0 tag=`wrong_logic`

<details><summary>Arm A raw_text</summary>

```diff
diff --git a/broken/activity.py b/broken/activity.py
index 064c95f..87e8bfe 100644
--- a/broken/activity.py
+++ b/broken/activity.py
@@ -2,7 +2,7 @@

 def insert_activity_sql() -> str:
-    # BUG: columns are type, content, created_at
+    # Fixed: columns are type, content, created_at
-    return "INSERT INTO skyeye_activity (action, details, timestamp) VALUES ($1,$2,$3)"
+    return "INSERT INTO skyeye_activity (type, content, created_at) VALUES ($1,$2,$3)"

 def looks_fixed(s: str) -> bool:
     t = s.lower()
     return "type" in t and "content" in t and "created_at" in t and "action" not in t
```

</details>

<details><summary>Arm B raw_text</summary>

```diff
--- a/broken/activity.py	2026-07-28 00:00:00
+++ b/broken/activity.py	2026-07-28 00:00:00
@@ -2,7 +2,7 @@

 def insert_activity_sql() -> str:
-    # BUG: columns are type, content, created_at
+    # Fixed: canonical skyeye_activity columns
-    return "INSERT INTO skyeye_activity (action, details, timestamp) VALUES ($1,$2,$3)"
+    return "INSERT INTO skyeye_activity (type, content, created_at) VALUES ($1,$2,$3)"

 def looks_fixed(s: str) -> bool:
     t = s.lower()

This diff patches the listed files. The file broken/activity.py had an INSERT statement using the columns action, details, timestamp, which is incorrect for the skyeye_activity table. The commit changes the column list to type, content, created_at, updating both the SQL string and the looks_fixed reference set. The hunk only shows a unified diff for broken/activity.py. There are no markdown fences in this change.
```

</details>

### `users_no_user_id_column`

- ARM A passed=False score=0.0 tag=`wrong_logic`
- ARM B passed=False score=0.0 tag=`wrong_logic`

<details><summary>Arm A raw_text</summary>

```diff
@@ -2,7 +2,7 @@

 def user_lookup_sql() -> str:
-    # BUG: users has username/id, not user_id
+    # Fixed: use username column
-     return "SELECT * FROM users WHERE user_id = $1"
+     return "SELECT * FROM users WHERE username = $1"

 def looks_fixed(s: str) -> bool:
     t = s.lower()
```

</details>

<details><summary>Arm B raw_text</summary>

```diff
--- a/broken/lookup.py	2026-07-28 00:00:00
+++ b/broken/lookup.py	2026-07-28 00:00:00
@@ -2,7 +2,7 @@

 def user_lookup_sql() -> str:
-    # BUG: users has username/id, not user_id
+    # Fixed: lookup by username
-    return "SELECT * FROM users WHERE user_id = $1"
+    return "SELECT * FROM users WHERE username = $1"

 def looks_fixed(s: str) -> bool:
     t = s.lower()

This patch changes the SQL query from using non-existent user_id to querying by username, which matches the column that actually exists in the users table. The looks_fixed function is updated to reflect the correct column name.
```

</details>

## Tag tally (Arm B failures emphasized)

| Tag | Count |
|-----|------:|
| `wrong_logic` | 5 |
| `B:wrong_logic` | 5 |

## Observations

- Arm A mean ≈0.292 vs Arm B ≈0.167 on n=6 packs × 2 arms (12 real rows).
- Partial scores (0.25) appear on Arm A apply-partial paths — not full pass.
- Do **not** curate training data from this n=12 set; wait for fuel-era n≥50.

