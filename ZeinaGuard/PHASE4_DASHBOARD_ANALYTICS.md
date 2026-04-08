# Phase 4: Dashboard & Analytics Implementation

## Overview

Phase 4 transforms the raw data collected by sensors and stored in Phase 3 into actionable intelligence. This phase implements the Command Center of ZeinaGuard, providing real-time metrics, historical trends, and security situational awareness.

## Key Features Implemented

### 1. Centralized Security Metrics
- **Real-time Counters**: Live count of critical threats, active sensors, and open incidents.
- **Security Score Gauge**: A visual representation of the overall network security posture.
- **Threat Severity Distribution**: Breaking down threats by severity level (Critical, High, Medium, Low).

### 2. Time-Series Analytics
- **24-Hour Threat Timeline**: Visualizing threat frequency and severity over the last 24 hours using Recharts.
- **Historical Trends**: Analyzing long-term data to identify patterns in wireless attacks.

### 3. Sensor Health Monitoring
- **Real-time Status**: Online/Offline/Degraded indicators for each deployed sensor.
- **Hardware Metrics**: Monitoring CPU and memory usage to ensure sensor reliability.
- **Signal Strength (RSSI)**: Tracking the physical environment's impact on sensor performance.

### 4. Database-Backed API Integration
- **Direct DB Queries**: Replacing all mock dashboard data with optimized SQLAlchemy queries.
- **Aggregated Data**: Using SQL functions (`count`, `func.date_trunc`) to calculate metrics efficiently.

## Components Created

### Frontend (`components/dashboard/`)
- `metrics-card.tsx` - Reusable KPI display component.
- `threat-timeline-chart.tsx` - Interactive line chart for threat history.
- `threat-score-gauge.tsx` - Visual gauge for security score.
- `real-time-event-feed.tsx` - Sidebar feed of the most recent security events.
- `sensor-heatmap.tsx` - Visualization of sensor signal strength.

### Backend (`backend/routes_dashboard.py`)
- `/api/dashboard/overview` - Combined metrics for the main dashboard.
- `/api/dashboard/threat-timeline` - 24-hour time-series data.
- `/api/dashboard/sensor-health` - Current health status of all sensors.

## Data Flow

1. **Sensors** detect wireless activity and send events via WebSocket.
2. **WebSocket Server** saves events to `threat_events` (TimescaleDB hypertable).
3. **Dashboard API** queries the database using `func.date_trunc` for efficient time-binning.
4. **Next.js Frontend** fetches data every 30 seconds and renders interactive charts.

## Performance Optimization

- **Indexing**: All queries use indices on `created_at` and `sensor_id`.
- **Pre-aggregation**: The dashboard uses a "summary" approach to avoid loading thousands of individual events.
- **Efficient Joins**: Joining `Sensor` and `SensorHealth` to get the latest status with a single query.

## Verification

1. **Metrics Accuracy**: Verify that "Total Threats" on the dashboard matches the database count.
2. **Timeline Integrity**: Confirm that events appear on the chart at the correct hour.
3. **Real-time Updates**: Simulate a threat and watch the dashboard counters update automatically.
