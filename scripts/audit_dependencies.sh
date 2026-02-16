#!/bin/bash
# =============================================================================
# Dependency Security Audit
# =============================================================================
# Run this before deployments to catch known vulnerabilities in packages.
#
# Usage:
#   ./scripts/audit_dependencies.sh          # Run all audits
#   ./scripts/audit_dependencies.sh --python  # Python only
#   ./scripts/audit_dependencies.sh --node    # Node.js only
#
# Prerequisites:
#   pip install pip-audit    (for Python)
#   npm install              (for Node.js — npm audit is built-in)
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

AUDIT_PYTHON=true
AUDIT_NODE=true

if [[ "${1:-}" == "--python" ]]; then
    AUDIT_NODE=false
elif [[ "${1:-}" == "--node" ]]; then
    AUDIT_PYTHON=false
fi

EXIT_CODE=0

# ─── Python Audit ─────────────────────────────────────────────────────────────
if $AUDIT_PYTHON; then
    echo -e "\n${YELLOW}═══ Python Dependency Audit ═══${NC}\n"

    if command -v pip-audit &>/dev/null; then
        echo "Running pip-audit on backend/requirements.txt..."
        if pip-audit -r "$PROJECT_ROOT/backend/requirements.txt" --strict 2>&1; then
            echo -e "${GREEN}[PASS] No known Python vulnerabilities found.${NC}"
        else
            echo -e "${RED}[FAIL] Python vulnerabilities detected — see above.${NC}"
            EXIT_CODE=1
        fi
    else
        echo -e "${YELLOW}[SKIP] pip-audit not installed. Install with: pip install pip-audit${NC}"
    fi

    # Check for unpinned packages (>= without upper bound)
    echo ""
    echo "Checking for unpinned (>=) dependencies..."
    UNPINNED=$(grep -c '>=' "$PROJECT_ROOT/backend/requirements.txt" 2>/dev/null || true)
    if [[ "$UNPINNED" -gt 0 ]]; then
        echo -e "${YELLOW}[WARN] $UNPINNED packages use >= without upper bound:${NC}"
        grep '>=' "$PROJECT_ROOT/backend/requirements.txt" | grep -v '^#'
    else
        echo -e "${GREEN}[PASS] All Python packages are pinned.${NC}"
    fi
fi

# ─── Node.js Audit (Admin Console) ───────────────────────────────────────────
if $AUDIT_NODE; then
    echo -e "\n${YELLOW}═══ Node.js Dependency Audit (Admin) ═══${NC}\n"

    if [[ -d "$PROJECT_ROOT/admin" && -f "$PROJECT_ROOT/admin/package.json" ]]; then
        cd "$PROJECT_ROOT/admin"
        if [[ -f "package-lock.json" ]] || [[ -f "node_modules/.package-lock.json" ]]; then
            if npm audit --omit=dev 2>&1; then
                echo -e "${GREEN}[PASS] No known Node.js vulnerabilities (admin).${NC}"
            else
                echo -e "${YELLOW}[WARN] Node.js vulnerabilities detected in admin — see above.${NC}"
                # Don't fail on npm audit since react-scripts has known unfixable transitive issues
            fi
        else
            echo -e "${YELLOW}[SKIP] No package-lock.json found. Run 'npm install' first.${NC}"
        fi
    fi

    # Dashboard React (if present)
    if [[ -d "$PROJECT_ROOT/dashboard-react" && -f "$PROJECT_ROOT/dashboard-react/package.json" ]]; then
        echo -e "\n${YELLOW}═══ Node.js Dependency Audit (Dashboard) ═══${NC}\n"
        cd "$PROJECT_ROOT/dashboard-react"
        if [[ -f "package-lock.json" ]] || [[ -f "node_modules/.package-lock.json" ]]; then
            if npm audit --omit=dev 2>&1; then
                echo -e "${GREEN}[PASS] No known Node.js vulnerabilities (dashboard).${NC}"
            else
                echo -e "${YELLOW}[WARN] Node.js vulnerabilities detected in dashboard — see above.${NC}"
            fi
        else
            echo -e "${YELLOW}[SKIP] No package-lock.json found. Run 'npm install' first.${NC}"
        fi
    fi
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
if [[ $EXIT_CODE -eq 0 ]]; then
    echo -e "${GREEN}Dependency audit completed — no critical issues.${NC}"
else
    echo -e "${RED}Dependency audit completed — CRITICAL issues found.${NC}"
fi
echo "═══════════════════════════════════════════"

exit $EXIT_CODE
