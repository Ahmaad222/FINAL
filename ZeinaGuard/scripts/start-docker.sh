#!/bin/bash

# ZeinaGuard Pro - Docker Startup Script
# This script automatically starts all services and performs health checks

set -e

echo "=========================================="
echo "ZeinaGuard Pro - Docker Startup"
echo "=========================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

echo "Starting Docker services..."
docker compose up -d

echo ""
echo "Waiting for services to start (30 seconds)..."
sleep 30

echo ""
echo "Service Status:"
docker compose ps

echo ""
echo "Waiting for database to be ready..."
for i in {1..30}; do
    if docker compose exec -T postgres pg_isready -U zeinaguard_user -d zeinaguard_db > /dev/null 2>&1; then
        echo "✓ PostgreSQL is ready"
        break
    fi
    echo "  Attempt $i/30 - waiting for PostgreSQL..."
    sleep 2
done

echo ""
echo "Health Checks:"
echo "- Flask API: http://localhost:5000/health"
echo "- Next.js: http://localhost:3000"
echo "- PgAdmin: http://localhost:5050 (admin@zeinaguard.local)"
echo ""

# Try health checks
echo "Verifying Flask API..."
if curl -s http://localhost:5000/health > /dev/null 2>&1; then
    echo "✓ Flask API is responding"
else
    echo "✗ Flask API health check failed (it may still be starting)"
fi

echo ""
echo "=========================================="
echo "ZeinaGuard Pro is starting up!"
echo "=========================================="
echo ""
echo "Access your services:"
echo "  Dashboard:  http://localhost:3000"
echo "  API:        http://localhost:5000"
echo "  PgAdmin:    http://localhost:5050"
echo ""
echo "To view logs: docker-compose logs -f"
echo "To stop:      docker-compose down"
echo ""
