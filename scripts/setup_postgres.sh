#!/bin/bash
# =============================================================================
# CLINICAL SOVEREIGNTY LAB — PostgreSQL Docker Setup
# =============================================================================
# Run this script to start PostgreSQL in Docker
# Usage: chmod +x scripts/setup_postgres.sh && ./scripts/setup_postgres.sh
# =============================================================================

set -e

echo "========================================"
echo "  PostgreSQL Docker Setup"
echo "========================================"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if container already exists
if docker ps -a --format '{{.Names}}' | grep -q '^nate_postgres$'; then
    echo "⚠️  Container 'nate_postgres' already exists."
    read -p "Do you want to remove it and start fresh? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Stopping and removing existing container..."
        docker stop nate_postgres 2>/dev/null || true
        docker rm nate_postgres 2>/dev/null || true
    else
        echo "Starting existing container..."
        docker start nate_postgres
        echo "✅ PostgreSQL is running"
        exit 0
    fi
fi

# Create and start PostgreSQL container
echo "Creating PostgreSQL container..."
docker run -d \
  --name nate_postgres \
  --restart unless-stopped \
  -e POSTGRES_USER=nate_admin \
  -e POSTGRES_PASSWORD='bicgyw-&sabto-dommiS' \
  -e POSTGRES_DB=little_nate \
  -p 5432:5432 \
  -v nate_postgres_data:/var/lib/postgresql/data \
  postgres:15-alpine

echo ""
echo "Waiting for PostgreSQL to be ready..."
sleep 5

# Check if PostgreSQL is ready
until docker exec nate_postgres pg_isready -U nate_admin -d little_nate > /dev/null 2>&1; do
    echo "  Waiting..."
    sleep 2
done

echo ""
echo "✅ PostgreSQL is running!"
echo ""
echo "Connection details:"
echo "  Host:     10.0.0.81"
echo "  Port:     5432"
echo "  Database: little_nate"
echo "  User:     nate_admin"
echo "  Password: bicgyw-&sabto-dommiS"
echo ""
echo "Connection string:"
echo "  postgresql://nate_admin:bicgyw-&sabto-dommiS@10.0.0.81:5432/little_nate"
echo ""
echo "To run database migrations:"
echo "  docker exec -i nate_postgres psql -U nate_admin -d little_nate < backend/migrations/001_schema.sql"
echo ""
