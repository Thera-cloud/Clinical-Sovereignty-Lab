#!/usr/bin/env bash
set -euo pipefail

# Credential Rotation Script for Sovereign Sanctuary
# Usage: ./rotate_credentials.sh <credential_type>
#
# Supported types:
#   db_admin      - Rotate nate_admin PostgreSQL password
#   db_app        - Rotate nate_app PostgreSQL password
#   redis         - Rotate Redis password
#   jwt           - Rotate JWT signing secret
#   audit_token   - Rotate SKYEYE_AUDIT_TOKEN
#   all_db        - Rotate both DB passwords
#   audit         - Run credential health audit (read-only)

SERVER="68.183.168.75"
ENV_FILE="/opt/clinical-sovereignty-lab/.env"
COMPOSE_FILE="/opt/clinical-sovereignty-lab/docker-compose.prod.yml"
PROJECT_DIR="/opt/clinical-sovereignty-lab"
BACKUP_DIR="/opt/clinical-sovereignty-lab/credential_backups"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

generate_password() {
    python3 -c "import secrets; print(secrets.token_urlsafe(32))"
}

generate_hex_token() {
    python3 -c "import secrets; print(secrets.token_hex(32))"
}

backup_env() {
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    ssh "root@${SERVER}" "mkdir -p ${BACKUP_DIR} && cp ${ENV_FILE} ${BACKUP_DIR}/.env.backup_${timestamp} && chmod 600 ${BACKUP_DIR}/.env.backup_${timestamp}"
    log_info "Backed up .env to ${BACKUP_DIR}/.env.backup_${timestamp}"
}

update_env_var() {
    local key="$1"
    local value="$2"
    ssh "root@${SERVER}" "sed -i 's|^${key}=.*|${key}=${value}|' ${ENV_FILE}"
    log_info "Updated ${key} in .env"
}

restart_services() {
    local services="${1:-backend bridge}"
    log_info "Restarting services: ${services}"
    ssh "root@${SERVER}" "cd ${PROJECT_DIR} && docker compose -f docker-compose.prod.yml up -d ${services}"
    sleep 15
}

verify_health() {
    log_info "Verifying system health..."
    local health
    health=$(ssh "root@${SERVER}" "curl -s http://localhost:8000/health" 2>/dev/null || echo '{"status":"unreachable"}')
    if echo "$health" | grep -q '"healthy"'; then
        log_info "Backend healthy"
    else
        log_error "Backend unhealthy: ${health}"
        return 1
    fi

    local startup
    startup=$(ssh "root@${SERVER}" "docker logs nate_backend --since 30s 2>&1 | grep 'STARTUP COMPLETE'" || echo "")
    if [ -n "$startup" ]; then
        log_info "$startup"
    fi

    local bridge_db
    bridge_db=$(ssh "root@${SERVER}" "docker logs nate_bridge --since 30s 2>&1 | grep 'UserStore ready'" || echo "")
    if [ -n "$bridge_db" ]; then
        log_info "Bridge: $bridge_db"
    else
        log_warn "Bridge UserStore status not confirmed yet"
    fi
}

rotate_db_admin() {
    log_info "=== Rotating nate_admin PostgreSQL password ==="
    local new_pass
    new_pass=$(generate_password)

    backup_env

    log_info "Changing PostgreSQL role password..."
    ssh "root@${SERVER}" "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"ALTER ROLE nate_admin WITH PASSWORD '${new_pass}';\""

    update_env_var "POSTGRES_PASSWORD" "$new_pass"

    local current_db_url
    current_db_url=$(ssh "root@${SERVER}" "grep '^DATABASE_URL=' ${ENV_FILE}")
    local new_db_url
    new_db_url=$(echo "$current_db_url" | sed "s|://nate_admin:[^@]*@|://nate_admin:${new_pass}@|")
    ssh "root@${SERVER}" "sed -i 's|^DATABASE_URL=.*|${new_db_url}|' ${ENV_FILE}"
    log_info "Updated DATABASE_URL in .env"

    restart_services "backend bridge"
    verify_health
    log_info "=== nate_admin password rotation complete ==="
}

rotate_db_app() {
    log_info "=== Rotating nate_app PostgreSQL password ==="
    local new_pass
    new_pass=$(generate_password)

    backup_env

    log_info "Changing PostgreSQL role password..."
    ssh "root@${SERVER}" "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"ALTER ROLE nate_app WITH PASSWORD '${new_pass}';\""

    update_env_var "NATE_APP_DB_PASSWORD" "$new_pass"

    restart_services "backend bridge"
    verify_health
    log_info "=== nate_app password rotation complete ==="
}

rotate_redis() {
    log_info "=== Rotating Redis password ==="
    local new_pass
    new_pass=$(generate_password)
    local old_pass
    old_pass=$(ssh "root@${SERVER}" "grep '^REDIS_PASSWORD=' ${ENV_FILE} | cut -d= -f2")

    backup_env

    log_info "Setting new Redis password via CONFIG SET..."
    ssh "root@${SERVER}" "docker exec nate_redis redis-cli -a '${old_pass}' --no-auth-warning CONFIG SET requirepass '${new_pass}'"

    update_env_var "REDIS_PASSWORD" "$new_pass"

    local current_redis_url
    current_redis_url=$(ssh "root@${SERVER}" "grep '^REDIS_URL=' ${ENV_FILE}")
    local new_redis_url
    new_redis_url=$(echo "$current_redis_url" | sed "s|redis://:[^@]*@|redis://:${new_pass}@|")
    ssh "root@${SERVER}" "sed -i 's|^REDIS_URL=.*|${new_redis_url}|' ${ENV_FILE}"
    log_info "Updated REDIS_URL in .env"

    restart_services "backend bridge"
    verify_health
    log_info "=== Redis password rotation complete ==="
}

rotate_jwt() {
    log_info "=== Rotating JWT secret ==="
    log_warn "This will invalidate ALL existing JWT tokens (REST API sessions)"
    local new_secret
    new_secret=$(generate_hex_token)

    backup_env
    update_env_var "JWT_SECRET" "$new_secret"

    restart_services "backend"
    verify_health
    log_info "=== JWT secret rotation complete ==="
}

rotate_audit_token() {
    log_info "=== Rotating SKYEYE_AUDIT_TOKEN ==="
    local new_token
    new_token=$(generate_hex_token)

    backup_env
    update_env_var "SKYEYE_AUDIT_TOKEN" "$new_token"

    restart_services "backend"

    sleep 5
    local registered
    registered=$(ssh "root@${SERVER}" "docker logs nate_backend --since 20s 2>&1 | grep 'SKYEYE_AUDIT_TOKEN registered'" || echo "")
    if [ -n "$registered" ]; then
        log_info "Audit token registered in Redis"
    else
        log_warn "Audit token registration not confirmed"
    fi

    verify_health
    log_info "=== SKYEYE_AUDIT_TOKEN rotation complete ==="
}

run_audit() {
    log_info "=== Credential Health Audit ==="

    echo ""
    log_info "Checking password strength..."
    ssh "root@${SERVER}" bash -s <<'AUDIT_SCRIPT'
ENV_FILE="/opt/clinical-sovereignty-lab/.env"
weak=0
while IFS='=' read -r key value; do
    # Skip empty lines, comments, non-secret vars
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    echo "$key" | grep -qiE 'KEY|SECRET|PASSWORD|TOKEN|SID' || continue
    # Skip Stripe price IDs and SIDs (not passwords)
    echo "$key" | grep -qiE 'STRIPE_PRICE|VERIFY_SID|MESSAGING_SERVICE_SID|ACCOUNT_SID' && continue

    val_len=${#value}
    if [ "$val_len" -lt 16 ]; then
        echo "  WEAK: ${key} (${val_len} chars — below 16 minimum)"
        weak=$((weak + 1))
    elif [ "$val_len" -lt 24 ]; then
        echo "  FAIR: ${key} (${val_len} chars)"
    fi
done < <(grep -E '^[A-Z_]+=.+' "$ENV_FILE")

if [ "$weak" -eq 0 ]; then
    echo "  All credentials meet minimum length requirements"
fi
AUDIT_SCRIPT

    echo ""
    log_info "Checking for duplicate credentials..."
    ssh "root@${SERVER}" bash -s <<'DEDUP_SCRIPT'
ENV_FILE="/opt/clinical-sovereignty-lab/.env"
grep -E '^[A-Z_]+=.+' "$ENV_FILE" | grep -iE 'KEY|SECRET|PASSWORD|TOKEN' | \
    grep -viE 'STRIPE_PRICE|VERIFY_SID|MESSAGING_SERVICE_SID|ACCOUNT_SID' | \
    awk -F= '{print $2}' | sort | uniq -d | while read -r dup; do
        echo "  DUPLICATE VALUE found in:"
        grep -F "=${dup}" "$ENV_FILE" | awk -F= '{print "    " $1}'
    done
echo "  Done"
DEDUP_SCRIPT

    echo ""
    log_info "Checking .env file permissions..."
    ssh "root@${SERVER}" "ls -la ${ENV_FILE} | awk '{print \"  Permissions: \" \$1 \" Owner: \" \$3 \":\" \$4}'"

    echo ""
    log_info "Checking credential backup count..."
    ssh "root@${SERVER}" "ls /opt/clinical-sovereignty-lab/credential_backups/.env.backup_* 2>/dev/null | wc -l | xargs -I{} echo '  {} backup(s) stored'"

    echo ""
    log_info "Checking for credentials in git history..."
    local git_secrets
    git_secrets=$(cd /Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2 && git log --all --diff-filter=A --name-only --format="" -- '*.env' '.env*' 2>/dev/null | head -5)
    if [ -n "$git_secrets" ]; then
        log_warn "Potential .env files tracked in git history:"
        echo "$git_secrets"
    else
        log_info "No .env files found in git history"
    fi

    echo ""
    log_info "=== Audit complete ==="
}

case "${1:-help}" in
    db_admin)    rotate_db_admin ;;
    db_app)      rotate_db_app ;;
    redis)       rotate_redis ;;
    jwt)         rotate_jwt ;;
    audit_token) rotate_audit_token ;;
    all_db)
        rotate_db_admin
        echo ""
        rotate_db_app
        ;;
    audit)       run_audit ;;
    *)
        echo "Usage: $0 <credential_type>"
        echo ""
        echo "Rotation commands:"
        echo "  db_admin      Rotate nate_admin PostgreSQL password"
        echo "  db_app        Rotate nate_app PostgreSQL password"
        echo "  redis         Rotate Redis password"
        echo "  jwt           Rotate JWT signing secret (invalidates sessions)"
        echo "  audit_token   Rotate SKYEYE_AUDIT_TOKEN"
        echo "  all_db        Rotate both DB passwords"
        echo ""
        echo "Audit commands:"
        echo "  audit         Run credential health audit (read-only)"
        ;;
esac
