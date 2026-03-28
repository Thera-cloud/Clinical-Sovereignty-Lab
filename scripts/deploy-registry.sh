#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Sovereign Deploy — DigitalOcean Container Registry
# Builds images locally, pushes to DO registry, pulls on server.
# Fixes: deploy drift, no rollback, build-on-server fragility.
# =============================================================================

REGISTRY="registry.digitalocean.com/sovereign-container-repo"
SERVER="root@68.183.168.75"
COMPOSE_FILE="docker-compose.prod.yml"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
TAG="${TIMESTAMP}-${GIT_SHA}"

SERVICES=("backend" "bridge" "admin")
DOCKERFILES=("backend/Dockerfile" "backend/Dockerfile.bridge" "admin/Dockerfile")
CONTEXTS=("backend" "backend" "admin")
IMAGE_NAMES=("nate-backend" "nate-bridge" "nate-admin")

usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  build       Build all images locally"
    echo "  push        Push images to DO registry"
    echo "  deploy      Pull and restart on server"
    echo "  all         Build + push + deploy (full pipeline)"
    echo "  rollback    Roll back to a previous tag"
    echo "  list-tags   List available tags in registry"
    echo "  status      Show what's running on server"
    echo ""
    echo "Options:"
    echo "  --service=NAME   Only build/push/deploy one service (backend|bridge|admin)"
    echo "  --tag=TAG        Use specific tag instead of auto-generated"
    echo ""
    echo "Examples:"
    echo "  $0 all                        # Full deploy"
    echo "  $0 all --service=backend      # Deploy only backend"
    echo "  $0 rollback --tag=20260313-143022-abc1234"
    echo "  $0 list-tags"
}

log() { echo "[$(date +%H:%M:%S)] $*"; }
err() { echo "[$(date +%H:%M:%S)] ERROR: $*" >&2; exit 1; }

parse_args() {
    SERVICE_FILTER=""
    CUSTOM_TAG=""
    for arg in "$@"; do
        case "$arg" in
            --service=*) SERVICE_FILTER="${arg#*=}" ;;
            --tag=*) CUSTOM_TAG="${arg#*=}" ;;
        esac
    done
    [ -n "$CUSTOM_TAG" ] && TAG="$CUSTOM_TAG"
}

get_indices() {
    if [ -n "$SERVICE_FILTER" ]; then
        for i in "${!SERVICES[@]}"; do
            [ "${SERVICES[$i]}" = "$SERVICE_FILTER" ] && echo "$i" && return
        done
        err "Unknown service: $SERVICE_FILTER (valid: backend, bridge, admin)"
    else
        seq 0 $(( ${#SERVICES[@]} - 1 ))
    fi
}

cmd_build() {
    log "Building images with tag: $TAG"
    for i in $(get_indices); do
        local name="${IMAGE_NAMES[$i]}"
        local dockerfile="${DOCKERFILES[$i]}"
        local context="${CONTEXTS[$i]}"
        local full_tag="${REGISTRY}/${name}:${TAG}"
        local latest_tag="${REGISTRY}/${name}:latest"

        log "  Building ${name} from ${dockerfile}..."
        docker build -t "$full_tag" -t "$latest_tag" -f "$dockerfile" "$context"
        log "  ✓ ${name} built"
    done
    log "All images built with tag: $TAG"
}

cmd_push() {
    log "Pushing images to ${REGISTRY}..."
    log "Authenticating with DO registry..."
    doctl registry login 2>/dev/null || err "doctl registry login failed. Run: doctl auth init"

    for i in $(get_indices); do
        local name="${IMAGE_NAMES[$i]}"
        local full_tag="${REGISTRY}/${name}:${TAG}"
        local latest_tag="${REGISTRY}/${name}:latest"

        log "  Pushing ${name}:${TAG}..."
        docker push "$full_tag"
        docker push "$latest_tag"
        log "  ✓ ${name} pushed"
    done
    log "All images pushed"
}

cmd_deploy() {
    log "Deploying tag ${TAG} to ${SERVER}..."

    log "  Authenticating server with DO registry..."
    ssh "$SERVER" "doctl registry login 2>/dev/null || echo 'WARN: doctl not on server, using existing docker auth'"

    for i in $(get_indices); do
        local name="${IMAGE_NAMES[$i]}"
        local full_tag="${REGISTRY}/${name}:${TAG}"

        log "  Pulling ${name}:${TAG} on server..."
        ssh "$SERVER" "docker pull ${full_tag}"
    done

    log "  Saving current image IDs for rollback record..."
    ssh "$SERVER" "docker ps --format '{{.Image}}' | sort > /opt/clinical-sovereignty-lab/.deploy-previous-images"

    log "  Updating image tags in compose override..."
    local override_content="services:"
    for i in $(get_indices); do
        local service="${SERVICES[$i]}"
        local name="${IMAGE_NAMES[$i]}"
        local full_tag="${REGISTRY}/${name}:${TAG}"
        override_content="${override_content}
  ${service}:
    image: ${full_tag}"
    done

    ssh "$SERVER" "cat > /opt/clinical-sovereignty-lab/docker-compose.registry.yml << 'COMPOSEEOF'
${override_content}
COMPOSEEOF"

    log "  Restarting services..."
    ssh "$SERVER" "cd /opt/clinical-sovereignty-lab && docker compose -f docker-compose.prod.yml -f docker-compose.registry.yml up -d"

    log "  Waiting for health checks (30s)..."
    sleep 30

    log "  Checking health..."
    local health
    health=$(ssh "$SERVER" "curl -sf http://localhost:8000/health 2>/dev/null || echo 'UNHEALTHY'")
    if echo "$health" | grep -q "healthy"; then
        log "  ✓ Backend healthy"
    else
        log "  ⚠ Backend health check: $health"
        log "  Check logs: ssh $SERVER 'docker logs nate_backend --tail 30'"
    fi

    local startup
    startup=$(ssh "$SERVER" "docker logs nate_backend --since 60s 2>&1 | grep 'STARTUP COMPLETE' | tail -1")
    [ -n "$startup" ] && log "  $startup"

    log "  Recording deploy: tag=$TAG"
    ssh "$SERVER" "echo '${TAG} $(date -u +%Y-%m-%dT%H:%M:%SZ)' >> /opt/clinical-sovereignty-lab/.deploy-history"

    log "Deploy complete: $TAG"
}

cmd_rollback() {
    [ -z "$CUSTOM_TAG" ] && err "Rollback requires --tag=TAG. Use '$0 list-tags' to see available."

    log "Rolling back to tag: $TAG"

    for i in $(get_indices); do
        local name="${IMAGE_NAMES[$i]}"
        local full_tag="${REGISTRY}/${name}:${TAG}"

        log "  Pulling ${name}:${TAG}..."
        ssh "$SERVER" "docker pull ${full_tag}"
    done

    local override_content="services:"
    for i in $(get_indices); do
        local service="${SERVICES[$i]}"
        local name="${IMAGE_NAMES[$i]}"
        local full_tag="${REGISTRY}/${name}:${TAG}"
        override_content="${override_content}
  ${service}:
    image: ${full_tag}"
    done

    ssh "$SERVER" "cat > /opt/clinical-sovereignty-lab/docker-compose.registry.yml << 'COMPOSEEOF'
${override_content}
COMPOSEEOF"

    ssh "$SERVER" "cd /opt/clinical-sovereignty-lab && docker compose -f docker-compose.prod.yml -f docker-compose.registry.yml up -d"

    log "  Waiting for health (30s)..."
    sleep 30

    local health
    health=$(ssh "$SERVER" "curl -sf http://localhost:8000/health 2>/dev/null || echo 'UNHEALTHY'")
    if echo "$health" | grep -q "healthy"; then
        log "  ✓ Rollback healthy"
    else
        log "  ⚠ Health check: $health"
    fi

    ssh "$SERVER" "echo 'ROLLBACK ${TAG} $(date -u +%Y-%m-%dT%H:%M:%SZ)' >> /opt/clinical-sovereignty-lab/.deploy-history"
    log "Rollback complete: $TAG"
}

cmd_list_tags() {
    log "Listing tags in registry..."
    for name in "${IMAGE_NAMES[@]}"; do
        echo "--- ${name} ---"
        doctl registry repository list-tags "$name" --format Tag,UpdatedAt 2>/dev/null || echo "  (no tags yet)"
    done
    echo ""
    echo "--- Deploy history (server) ---"
    ssh "$SERVER" "cat /opt/clinical-sovereignty-lab/.deploy-history 2>/dev/null || echo '  (no deploys yet)'"
}

cmd_status() {
    log "Server container status:"
    ssh "$SERVER" "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'"
    echo ""
    log "Last deploy:"
    ssh "$SERVER" "tail -3 /opt/clinical-sovereignty-lab/.deploy-history 2>/dev/null || echo '  (no deploys yet)'"
}

# --- Main ---
[ $# -lt 1 ] && { usage; exit 0; }

COMMAND="$1"
shift
parse_args "$@"

case "$COMMAND" in
    build)     cmd_build ;;
    push)      cmd_push ;;
    deploy)    cmd_deploy ;;
    all)       cmd_build && cmd_push && cmd_deploy ;;
    rollback)  cmd_rollback ;;
    list-tags) cmd_list_tags ;;
    status)    cmd_status ;;
    *)         usage; exit 1 ;;
esac
