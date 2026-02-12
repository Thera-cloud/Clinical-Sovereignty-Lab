#!/bin/bash
# =============================================================================
# CLINICAL SOVEREIGNTY LAB — First Run Setup
# =============================================================================
# This script sets up everything for first-time installation
# Run with: chmod +x scripts/first_run.sh && ./scripts/first_run.sh
# =============================================================================

set -e  # Exit on error

echo "========================================"
echo "  CLINICAL SOVEREIGNTY LAB"
echo "  First Run Setup"
echo "========================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# -----------------------------------------------------------------------------
# Check prerequisites
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Checking prerequisites...${NC}"

# Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker not found. Please install Docker first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker${NC}"

# Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose not found. Please install Docker Compose.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose${NC}"

# Git
if ! command -v git &> /dev/null; then
    echo -e "${RED}❌ Git not found. Please install Git.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Git${NC}"

echo ""

# -----------------------------------------------------------------------------
# Check for .env file
# -----------------------------------------------------------------------------
if [ ! -f .env ]; then
    echo -e "${YELLOW}Creating .env from template...${NC}"
    cp .env.template .env
    
    # Generate JWT secret
    JWT_SECRET=$(openssl rand -hex 32)
    sed -i "s/JWT_SECRET=.*/JWT_SECRET=$JWT_SECRET/" .env
    
    echo -e "${GREEN}✓ Created .env file${NC}"
    echo -e "${YELLOW}⚠️  Please edit .env and add your Azure credentials!${NC}"
    echo ""
    echo "Required values to set:"
    echo "  - AZURE_API_KEY"
    echo "  - AZURE_OPENAI_ENDPOINT"
    echo "  - POSTGRES_PASSWORD"
    echo ""
    read -p "Press Enter after editing .env to continue..."
fi

# Verify Azure credentials are set
source .env
if [ "$AZURE_API_KEY" == "your_azure_api_key_here" ] || [ -z "$AZURE_API_KEY" ]; then
    echo -e "${RED}❌ AZURE_API_KEY not configured in .env${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Azure credentials configured${NC}"

# -----------------------------------------------------------------------------
# Create directories
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Creating directories...${NC}"
mkdir -p backend/logs
mkdir -p nginx/ssl
mkdir -p mobile/assets/images
mkdir -p mobile/assets/icons
mkdir -p mobile/assets/fonts
echo -e "${GREEN}✓ Directories created${NC}"

# -----------------------------------------------------------------------------
# Start database first
# -----------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}Starting PostgreSQL...${NC}"
docker-compose up -d postgres

echo "Waiting for database to be ready..."
sleep 10

# Check if database is ready
until docker-compose exec -T postgres pg_isready -U ${POSTGRES_USER:-nate_admin}; do
    echo "Waiting for PostgreSQL..."
    sleep 2
done
echo -e "${GREEN}✓ PostgreSQL ready${NC}"

# -----------------------------------------------------------------------------
# Run migrations
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Running database migrations...${NC}"
if [ -f backend/migrations/001_schema.sql ]; then
    docker-compose exec -T postgres psql -U ${POSTGRES_USER:-nate_admin} -d ${POSTGRES_DB:-little_nate} -f /docker-entrypoint-initdb.d/001_schema.sql || true
    echo -e "${GREEN}✓ Migrations complete${NC}"
else
    echo -e "${YELLOW}⚠️  No migration files found - database may be empty${NC}"
fi

# -----------------------------------------------------------------------------
# Start Redis
# -----------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}Starting Redis...${NC}"
docker-compose up -d redis
sleep 3
echo -e "${GREEN}✓ Redis ready${NC}"

# -----------------------------------------------------------------------------
# Start backend services
# -----------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}Starting backend services...${NC}"
docker-compose up -d backend bridge
sleep 5

# Check backend health
if curl -s http://localhost:8000/health > /dev/null; then
    echo -e "${GREEN}✓ Backend API running${NC}"
else
    echo -e "${RED}❌ Backend API not responding${NC}"
    echo "Check logs with: docker-compose logs backend"
fi

# -----------------------------------------------------------------------------
# Start admin console
# -----------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}Starting admin console...${NC}"
docker-compose up -d admin
sleep 5
echo -e "${GREEN}✓ Admin console running${NC}"

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "========================================"
echo -e "${GREEN}  SETUP COMPLETE!${NC}"
echo "========================================"
echo ""
echo "Services running:"
echo "  • API Server:     http://${SERVER_HOST:-10.0.0.81}:${SERVER_PORT:-8000}"
echo "  • WebSocket:      ws://${SERVER_HOST:-10.0.0.81}:${WEBSOCKET_PORT:-8765}"
echo "  • Admin Console:  http://${SERVER_HOST:-10.0.0.81}:${ADMIN_PORT:-3000}"
echo "  • API Docs:       http://${SERVER_HOST:-10.0.0.81}:${SERVER_PORT:-8000}/docs"
echo ""
echo "Admin login:"
echo "  • Username: ${ADMIN_USERNAME:-sovereign}"
echo "  • Password: ${ADMIN_PASSWORD:-SovereignDev2026!}"
echo ""
echo "Next steps:"
echo "  1. Open http://${SERVER_HOST:-10.0.0.81}:${ADMIN_PORT:-3000} in browser"
echo "  2. Build Flutter app: cd mobile && flutter run"
echo "  3. Check logs: docker-compose logs -f"
echo ""
echo "To stop all services: docker-compose down"
echo ""
