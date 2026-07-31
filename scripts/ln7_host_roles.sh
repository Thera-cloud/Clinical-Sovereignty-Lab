#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — LN7 host-role contract (Attempt 4 / seam-7 pattern fix).
#
# Three named roles. Scripts must not inherit host/target/credential context
# implicitly from "wherever they happen to run."
#
#   LN7_AUTH_BASE   HTTP origin for bakeoff/scorecard (e.g. http://127.0.0.1:8000)
#   LN7_ORCH_HOST   Orchestrator identity: blue | green (auto-detected if unset)
#   LN7_BURST_SSH   root@$DROPLET_IP from handoff / provision only — never GREEN
#
# Legacy LN7_GREEN_HOST remains as the *remote* SSH peer when orch=blue.
# When orch=green, GREEN work is local (cp/curl/docker); SSH to 127.0.0.1 is refuse.
#
# Source:  # shellcheck source=scripts/ln7_host_roles.sh
#          source "$REPO/scripts/ln7_host_roles.sh"
#
# shellcheck shell=bash
# Do not set -e here — this file is sourced; callers own errexit.

_ln7_host_roles_loaded=1

ln7_detect_orch_host() {
  if [[ -n "${LN7_ORCH_HOST:-}" ]]; then
    echo "$LN7_ORCH_HOST"
    return
  fi
  if [[ -d /opt/clinical-sovereignty-lab/backend/app ]] \
     && [[ -f /opt/clinical-sovereignty-lab/docker-compose.prod.yml ]]; then
    echo green
    return
  fi
  echo blue
}

# Resolve AUTH_BASE / ORCH / remote GREEN SSH peer (blue orch only).
ln7_resolve_host_roles() {
  LN7_ORCH_HOST="$(ln7_detect_orch_host)"
  export LN7_ORCH_HOST

  if [[ -z "${LN7_AUTH_BASE:-}" ]]; then
    if [[ "$LN7_ORCH_HOST" == "green" ]]; then
      LN7_AUTH_BASE="http://127.0.0.1:8000"
    else
      # BLUE orch talks to GREEN API over public HTTPS (not SSH-to-self).
      LN7_AUTH_BASE="${LN7_AUTH_BASE_DEFAULT:-https://api.sovereignsanctuary.net}"
    fi
  fi
  export LN7_AUTH_BASE

  # Remote SSH peer for GREEN filesystem/docker when orch is NOT on GREEN.
  # Never default this to loopback.
  if [[ "$LN7_ORCH_HOST" == "green" ]]; then
    LN7_GREEN_SSH=""
    LN7_GREEN_EXEC_MODE=local
  else
    LN7_GREEN_SSH="${LN7_GREEN_HOST:-root@68.183.168.75}"
    LN7_GREEN_EXEC_MODE=ssh
    ln7_assert_not_loopback_ssh "$LN7_GREEN_SSH" "LN7_GREEN_HOST/LN7_GREEN_SSH" || return $?
  fi
  export LN7_GREEN_SSH LN7_GREEN_EXEC_MODE
}

ln7_ssh_target_host() {
  local spec="$1"
  local h="${spec##*@}"
  h="${h%%:*}"
  echo "$h"
}

ln7_is_loopback_host() {
  local h
  h="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
  case "$h" in
    ""|localhost|localhost.*|127.*|::1|0:0:0:0:0:0:0:1) return 0 ;;
  esac
  return 1
}

# Fail-closed: SSH targets must never be this machine's loopback.
ln7_assert_not_loopback_ssh() {
  local spec="$1" label="${2:-ssh_target}"
  local h
  h="$(ln7_ssh_target_host "$spec")"
  if ln7_is_loopback_host "$h"; then
    echo "[ln7_host_roles] REFUSE $label=$spec — loopback SSH is seam-7; use LN7_GREEN_EXEC_MODE=local / LN7_AUTH_BASE" >&2
    return 3
  fi
  return 0
}

# BURST_SSH must be set from droplet IP / handoff only.
ln7_set_burst_ssh() {
  local ip="$1"
  [[ -n "$ip" ]] || { echo "[ln7_host_roles] REFUSE empty burst IP" >&2; return 3; }
  if ln7_is_loopback_host "$ip"; then
    echo "[ln7_host_roles] REFUSE BURST_SSH loopback ip=$ip" >&2
    return 3
  fi
  LN7_BURST_SSH="root@${ip}"
  export LN7_BURST_SSH
  ln7_assert_not_loopback_ssh "$LN7_BURST_SSH" "LN7_BURST_SSH" || return $?
}

# Run a command on GREEN: local when orch=green, else SSH (non-loopback).
# Usage: ln7_green_run <ssh_opts array name optional> -- command...
# Simpler API: ln7_green_bash 'script'
ln7_green_bash() {
  local script="$1"
  ln7_resolve_host_roles
  if [[ "${LN7_GREEN_EXEC_MODE}" == "local" ]]; then
    bash -c "$script"
  else
    # shellcheck disable=SC2086
    ssh ${LN7_SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=30} "$LN7_GREEN_SSH" "bash -c $(printf '%q' "$script")"
  fi
}

# Copy local file to GREEN handoff path (cp when local, scp when remote).
ln7_green_install_file() {
  local src="$1" dest="$2"
  ln7_resolve_host_roles
  if [[ "${LN7_GREEN_EXEC_MODE}" == "local" ]]; then
    mkdir -p "$(dirname "$dest")"
    cp -f "$src" "$dest"
    chown 1000:1000 "$dest" 2>/dev/null || true
    chmod 640 "$dest" 2>/dev/null || true
  else
    # shellcheck disable=SC2086
    scp ${LN7_SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=30} "$src" "$LN7_GREEN_SSH:$dest" >/dev/null
    # shellcheck disable=SC2086
    ssh ${LN7_SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=30} "$LN7_GREEN_SSH" \
      "chown 1000:1000 '$dest'; chmod 640 '$dest'" || true
  fi
}

ln7_green_mv_destroyed() {
  local path="$1"
  ln7_resolve_host_roles
  if [[ "${LN7_GREEN_EXEC_MODE}" == "local" ]]; then
    mv -f "$path" "${path}.destroyed" 2>/dev/null || true
  else
    # shellcheck disable=SC2086
    ssh ${LN7_SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=30} "$LN7_GREEN_SSH" \
      "mv -f '$path' '${path}.destroyed' 2>/dev/null || true" || true
  fi
}

# Destroy with mandatory retry + 404 confirmation. Never "ANOMALY then walk away"
# while the resource still GETs. Returns 0 only when GET is 404/gone.
ln7_destroy_droplet_verified() {
  local id="$1"
  local max="${2:-8}"
  local i out
  [[ -n "$id" ]] || return 0
  for i in $(seq 1 "$max"); do
    doctl compute droplet delete "$id" --force >/dev/null 2>&1 || true
    sleep $(( 2 + i ))
    if out="$(doctl compute droplet get "$id" --format ID,Status --no-header 2>&1)"; then
      echo "[ln7_host_roles] destroy poll $i/$max still active: $out" >&2
      continue
    fi
    # Non-zero get → treat as gone if message looks like 404
    if echo "$out" | grep -qiE '404|could not be found|not found'; then
      echo "[ln7_host_roles] destroy verified id=$id (404 after attempt $i)" >&2
      return 0
    fi
    # Some doctl versions: empty error — re-get
    if ! doctl compute droplet get "$id" >/dev/null 2>&1; then
      echo "[ln7_host_roles] destroy verified id=$id (gone after attempt $i)" >&2
      return 0
    fi
  done
  echo "[ln7_host_roles] ANOMALY billing_resource_still_alive id=$id — NOT walking away; last get:" >&2
  doctl compute droplet get "$id" --format ID,Name,Status,PublicIPv4 --no-header 2>&1 || true
  return 4
}

# Offline self-test: nonexistent id must report verified-gone (no paid droplet).
ln7_destroy_path_selftest() {
  local fake="${LN7_DESTROY_SELFTEST_ID:-999999999}"
  if ! command -v doctl >/dev/null 2>&1; then
    echo "[ln7_host_roles] SKIP destroy selftest — doctl missing" >&2
    return 0
  fi
  if doctl account get >/dev/null 2>&1; then
    ln7_destroy_droplet_verified "$fake" 3
    return $?
  fi
  echo "[ln7_host_roles] SKIP destroy selftest — doctl not authenticated" >&2
  return 0
}

# Paid burst gate: host-contract patch alone must not spend GPU on starved adapters.
ln7_assert_paid_burst_allowed() {
  if [[ "${LN7_BURST_DRY_RUN:-0}" == "1" ]]; then
    return 0
  fi
  if [[ "${LN7_BURST_ALLOW_PAID:-0}" == "1" ]]; then
    return 0
  fi
  echo "[ln7_host_roles] REFUSE paid provision — set LN7_BURST_ALLOW_PAID=1 only after ≥300 organic G1 rows AND reviewed host-contract on main (Attempt 4 sequencing)" >&2
  return 9
}
