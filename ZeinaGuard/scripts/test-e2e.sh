#!/bin/bash

# ZeinaGuard Pro - E2E Health Check Script (Improved)

set -e

API_URL="${API_URL:-[http://localhost:5000}](http://localhost:5000})"
BASE_URL="${BASE_URL:-[http://localhost:3000}](http://localhost:3000})"
MAX_RETRIES=10
SLEEP_TIME=3

echo "=========================================="
echo "ZeinaGuard Pro - E2E Health Check"
echo "=========================================="
echo ""
echo "API: $API_URL"
echo "Frontend: $BASE_URL"
echo ""

# 🔁 Retry function

retry_check() {
local url=$1
local name=$2

for ((i=1; i<=MAX_RETRIES; i++)); do
if curl -sf "$url" > /dev/null; then
echo "   ✓ $name is ready"
return 0
fi
echo "   ⏳ Waiting for $name... ($i/$MAX_RETRIES)"
sleep $SLEEP_TIME
done

echo "   ✗ $name failed after retries"
return 1
}

# 1. Backend health

echo "1. Backend health..."
retry_check "$API_URL/health" "Backend" || exit 1

# 2. API endpoints

echo ""
echo "2. API endpoints..."

ENDPOINTS=(
"/api/sensors"
"/api/alerts"
"/api/dashboard/overview"
"/api/dashboard/incident-summary"
)

for EP in "${ENDPOINTS[@]}"; do
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL$EP")

if [ "$STATUS" = "200" ]; then
echo "   ✓ $EP (200)"
else
echo "   ✗ $EP ($STATUS)"
fi
done

# 3. Frontend check

echo ""
echo "3. Frontend check..."

if curl -sf "$BASE_URL" > /dev/null; then
echo "   ✓ Frontend is accessible"
else
echo "   ⚠ Frontend not responding yet"
fi

echo ""
echo "=========================================="
echo "Health check complete"
echo "=========================================="
echo ""
echo "Manual checks:"
echo "  - Dashboard: $BASE_URL"
echo "  - Incidents: $BASE_URL/incidents"
echo ""

echo "Tip:"
echo "If something fails, run:"
echo "  docker compose logs -f"
