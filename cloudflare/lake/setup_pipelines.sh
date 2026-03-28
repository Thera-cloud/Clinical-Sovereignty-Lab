#!/usr/bin/env bash
#
# Sovereign Sanctuary — Iceberg Data Lake Pipeline Setup
#
# Creates Cloudflare Pipeline streams, sinks, and pipelines for 10 PostgreSQL
# tables that get offloaded to Apache Iceberg tables in R2 for analytics.
#
# Prerequisites:
#   1. R2 bucket "nate-analytics" created with Data Catalog enabled
#   2. WRANGLER_R2_SQL_AUTH_TOKEN exported (Cloudflare API token with
#      R2 Storage + R2 Data Catalog + Workers Pipelines + R2 SQL perms)
#   3. wrangler logged in (npx wrangler login)
#
# Usage:
#   export WRANGLER_R2_SQL_AUTH_TOKEN=your-api-token
#   bash setup_pipelines.sh
#
set -euo pipefail

BUCKET="nate-analytics"
NAMESPACE="sanctuary"
TOKEN="${WRANGLER_R2_SQL_AUTH_TOKEN:?Set WRANGLER_R2_SQL_AUTH_TOKEN}"
ROLL_INTERVAL=60  # Write Iceberg files every 60 seconds

echo "=== Sovereign Sanctuary Iceberg Data Lake Setup ==="
echo "Bucket: $BUCKET | Namespace: $NAMESPACE | Roll: ${ROLL_INTERVAL}s"
echo ""

# ---------------------------------------------------------------------------
# Table schemas (Cloudflare Pipeline JSON schema format)
# ---------------------------------------------------------------------------
SCHEMAS_DIR=$(mktemp -d)
trap "rm -rf $SCHEMAS_DIR" EXIT

# 1. conversation_history
cat > "$SCHEMAS_DIR/conversation_history.json" << 'EOF'
{
  "fields": [
    { "name": "id", "type": "int64", "required": true },
    { "name": "user_id", "type": "string", "required": true },
    { "name": "session_id", "type": "string", "required": false },
    { "name": "user_text", "type": "string", "required": false },
    { "name": "ai_text", "type": "string", "required": false },
    { "name": "word_count_user", "type": "int64", "required": false },
    { "name": "word_count_ai", "type": "int64", "required": false },
    { "name": "me2me_absorbed", "type": "bool", "required": false },
    { "name": "content_encrypted", "type": "bool", "required": false },
    { "name": "created_at", "type": "string", "required": true },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# 2. skyeye_activity
cat > "$SCHEMAS_DIR/skyeye_activity.json" << 'EOF'
{
  "fields": [
    { "name": "id", "type": "int64", "required": true },
    { "name": "platform", "type": "string", "required": false },
    { "name": "type", "type": "string", "required": true },
    { "name": "content", "type": "string", "required": false },
    { "name": "pillar", "type": "string", "required": false },
    { "name": "severity", "type": "string", "required": false },
    { "name": "created_at", "type": "string", "required": true },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# 3. token_transactions
cat > "$SCHEMAS_DIR/token_transactions.json" << 'EOF'
{
  "fields": [
    { "name": "id", "type": "string", "required": true },
    { "name": "username", "type": "string", "required": true },
    { "name": "action", "type": "string", "required": true },
    { "name": "amount", "type": "int64", "required": true },
    { "name": "balance_before", "type": "int64", "required": true },
    { "name": "balance_after", "type": "int64", "required": true },
    { "name": "reason", "type": "string", "required": false },
    { "name": "initiated_by", "type": "string", "required": false },
    { "name": "source", "type": "string", "required": false },
    { "name": "created_at", "type": "string", "required": true },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# 4. nevedal_metrics
cat > "$SCHEMAS_DIR/nevedal_metrics.json" << 'EOF'
{
  "fields": [
    { "name": "id", "type": "int64", "required": true },
    { "name": "user_id", "type": "string", "required": true },
    { "name": "session_id", "type": "string", "required": false },
    { "name": "c_emo", "type": "float64", "required": false },
    { "name": "p_ent", "type": "float64", "required": false },
    { "name": "t_tunnel", "type": "float64", "required": false },
    { "name": "gamma_env", "type": "float64", "required": false },
    { "name": "e_g_joint", "type": "float64", "required": false },
    { "name": "tau_emo", "type": "float64", "required": false },
    { "name": "d_distance", "type": "float64", "required": false },
    { "name": "cee_window", "type": "bool", "required": false },
    { "name": "cee_duration_seconds", "type": "int64", "required": false },
    { "name": "recorded_at", "type": "string", "required": true },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# 5. wisdom_extractions
cat > "$SCHEMAS_DIR/wisdom_extractions.json" << 'EOF'
{
  "fields": [
    { "name": "id", "type": "string", "required": true },
    { "name": "user_id", "type": "string", "required": false },
    { "name": "family_id", "type": "string", "required": false },
    { "name": "session_id", "type": "string", "required": false },
    { "name": "insight_type", "type": "string", "required": true },
    { "name": "content", "type": "string", "required": true },
    { "name": "effectiveness_score", "type": "float64", "required": false },
    { "name": "source", "type": "string", "required": false },
    { "name": "approved", "type": "bool", "required": false },
    { "name": "extracted_at", "type": "string", "required": true },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# 6. me2me_imprint_entries
cat > "$SCHEMAS_DIR/me2me_imprint_entries.json" << 'EOF'
{
  "fields": [
    { "name": "entry_id", "type": "string", "required": true },
    { "name": "user_id", "type": "string", "required": true },
    { "name": "source", "type": "string", "required": false },
    { "name": "content", "type": "string", "required": false },
    { "name": "c_emo_at_capture", "type": "float64", "required": false },
    { "name": "gamma_at_capture", "type": "float64", "required": false },
    { "name": "captured_at", "type": "string", "required": false },
    { "name": "processed", "type": "bool", "required": false },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# 7. skyeye_post_analytics
cat > "$SCHEMAS_DIR/skyeye_post_analytics.json" << 'EOF'
{
  "fields": [
    { "name": "id", "type": "int64", "required": true },
    { "name": "platform", "type": "string", "required": true },
    { "name": "post_id", "type": "string", "required": true },
    { "name": "post_url", "type": "string", "required": false },
    { "name": "post_text", "type": "string", "required": false },
    { "name": "likes", "type": "int64", "required": false },
    { "name": "reposts", "type": "int64", "required": false },
    { "name": "comments", "type": "int64", "required": false },
    { "name": "impressions", "type": "int64", "required": false },
    { "name": "captured_at", "type": "string", "required": false },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# 8. skyeye_notifications
cat > "$SCHEMAS_DIR/skyeye_notifications.json" << 'EOF'
{
  "fields": [
    { "name": "id", "type": "int64", "required": true },
    { "name": "platform", "type": "string", "required": true },
    { "name": "notification_type", "type": "string", "required": true },
    { "name": "post_id", "type": "string", "required": false },
    { "name": "actor_handle", "type": "string", "required": true },
    { "name": "actor_id", "type": "string", "required": false },
    { "name": "actor_followers", "type": "int64", "required": false },
    { "name": "processed", "type": "bool", "required": false },
    { "name": "created_at", "type": "string", "required": false },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# 9. coaching_sessions
cat > "$SCHEMAS_DIR/coaching_sessions.json" << 'EOF'
{
  "fields": [
    { "name": "id", "type": "string", "required": true },
    { "name": "client_id", "type": "string", "required": true },
    { "name": "coach_id", "type": "string", "required": true },
    { "name": "status", "type": "string", "required": true },
    { "name": "price_cents", "type": "int64", "required": false },
    { "name": "duration_minutes", "type": "int64", "required": false },
    { "name": "payment_status", "type": "string", "required": false },
    { "name": "payment_amount_cents", "type": "int64", "required": false },
    { "name": "scheduled_at", "type": "string", "required": false },
    { "name": "started_at", "type": "string", "required": false },
    { "name": "ended_at", "type": "string", "required": false },
    { "name": "created_at", "type": "string", "required": true },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# 10. skyeye_sessions
cat > "$SCHEMAS_DIR/skyeye_sessions.json" << 'EOF'
{
  "fields": [
    { "name": "id", "type": "int64", "required": true },
    { "name": "session_start", "type": "string", "required": false },
    { "name": "session_end", "type": "string", "required": false },
    { "name": "total_actions", "type": "int64", "required": false },
    { "name": "status", "type": "string", "required": true },
    { "name": "notes", "type": "string", "required": false },
    { "name": "created_at", "type": "string", "required": true },
    { "name": "cdc_op", "type": "string", "required": false }
  ]
}
EOF

# ---------------------------------------------------------------------------
# Create streams, sinks, and pipelines for each table
# ---------------------------------------------------------------------------
TABLES=(
  conversation_history
  skyeye_activity
  token_transactions
  nevedal_metrics
  wisdom_extractions
  me2me_imprint_entries
  skyeye_post_analytics
  skyeye_notifications
  coaching_sessions
  skyeye_sessions
)

for TABLE in "${TABLES[@]}"; do
  STREAM_NAME="cdc_${TABLE}_stream"
  SINK_NAME="cdc_${TABLE}_sink"
  PIPELINE_NAME="cdc_${TABLE}_pipeline"

  echo "--- Setting up: $TABLE ---"

  # Create stream
  echo "  Creating stream: $STREAM_NAME"
  npx wrangler pipelines streams create "$STREAM_NAME" \
    --schema-file "$SCHEMAS_DIR/${TABLE}.json" \
    --http-enabled true \
    --http-auth true \
    2>&1 | grep -E "Endpoint|stream_id|Successfully" || true

  # Create sink
  echo "  Creating sink: $SINK_NAME"
  npx wrangler pipelines sinks create "$SINK_NAME" \
    --type "r2-data-catalog" \
    --bucket "$BUCKET" \
    --roll-interval "$ROLL_INTERVAL" \
    --namespace "$NAMESPACE" \
    --table "$TABLE" \
    --catalog-token "$TOKEN" \
    2>&1 | grep -E "Successfully|Error" || true

  # Create pipeline
  echo "  Creating pipeline: $PIPELINE_NAME"
  npx wrangler pipelines create "$PIPELINE_NAME" \
    --sql "INSERT INTO ${SINK_NAME} SELECT * FROM ${STREAM_NAME}" \
    2>&1 | grep -E "Successfully|Error" || true

  echo ""
done

echo "=== Pipeline setup complete ==="
echo "Warehouse: 8350b355ec3c721d5f1853e80970d3c1_nate-analytics"
echo ""
echo "Test query:"
echo "  npx wrangler r2 sql query '8350b355ec3c721d5f1853e80970d3c1_nate-analytics' \\"
echo "    'SELECT COUNT(*) FROM sanctuary.conversation_history'"
