-- TimescaleDB Extension and Hypertable Configuration
-- This script converts regular tables into hypertables for optimal time-series performance

SELECT 'Enabling TimescaleDB Extension...' AS info;
-- Ensure TimescaleDB extension is created
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

SELECT 'Converting tables to hypertables...' AS info;
-- Convert threat_events to hypertable
SELECT create_hypertable('threat_events', 'time', if_not_exists => TRUE);

-- Convert sensor_health to hypertable
SELECT create_hypertable('sensor_health', 'created_at', if_not_exists => TRUE);

-----------------------------------------------------------
-- 1. تفعيل الضغط أولاً (CRITICAL: Must happen before policies)
-----------------------------------------------------------
ALTER TABLE threat_events SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC',
    timescaledb.compress_segmentby = 'threat_id, sensor_id'
);

ALTER TABLE sensor_health SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'created_at DESC',
    timescaledb.compress_segmentby = 'sensor_id'
);

-----------------------------------------------------------
-- 2. إضافة سياسات الضغط (Compression Policies)
-----------------------------------------------------------
-- Set up automatic data compression for old data (> 7 days)
SELECT add_compression_policy('threat_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('sensor_health', INTERVAL '7 days', if_not_exists => TRUE);

-----------------------------------------------------------
-- 3. الجداول المحسنة للتقارير (Continuous Aggregates)
-----------------------------------------------------------
-- Daily threat summary
CREATE MATERIALIZED VIEW IF NOT EXISTS threat_events_daily 
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) as bucket,
    threat_id,
    sensor_id,
    COUNT(*) as event_count,
    AVG(packet_count) as avg_packets,
    MAX(signal_strength) as max_signal,
    MIN(signal_strength) as min_signal
FROM threat_events
GROUP BY bucket, threat_id, sensor_id;

-- Hourly threat summary
CREATE MATERIALIZED VIEW IF NOT EXISTS threat_events_hourly 
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) as bucket,
    threat_id,
    sensor_id,
    COUNT(*) as event_count,
    AVG(packet_count) as avg_packets
FROM threat_events
GROUP BY bucket, threat_id, sensor_id;

-- Sensor health daily summary
CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_health_daily 
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', created_at) as bucket,
    sensor_id,
    AVG(CAST(signal_strength AS FLOAT)) as avg_signal,
    AVG(cpu_usage) as avg_cpu,
    AVG(memory_usage) as avg_memory,
    MAX(uptime) as max_uptime
FROM sensor_health
GROUP BY bucket, sensor_id;

-----------------------------------------------------------
-- 4. سياسات التحديث (Refresh Policies)
-----------------------------------------------------------
SELECT add_continuous_aggregate_policy('threat_events_daily',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('threat_events_hourly',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('sensor_health_daily',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-----------------------------------------------------------
-- 5. سياسات مسح البيانات القديمة (Retention Policies)
-----------------------------------------------------------
SELECT add_retention_policy('threat_events', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_retention_policy('sensor_health', INTERVAL '90 days', if_not_exists => TRUE);

-----------------------------------------------------------
-- 6. الفهارس الإضافية (Extra Indexes)
-----------------------------------------------------------
CREATE INDEX IF NOT EXISTS threat_events_threat_time ON threat_events (threat_id, time DESC);
CREATE INDEX IF NOT EXISTS threat_events_sensor_time ON threat_events (sensor_id, time DESC);
CREATE INDEX IF NOT EXISTS sensor_health_sensor_time ON sensor_health (sensor_id, created_at DESC);

-----------------------------------------------------------
-- 7. الصلاحيات (Permissions)
-----------------------------------------------------------
GRANT ALL ON ALL TABLES IN SCHEMA public TO zeinaguard_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO zeinaguard_user;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO zeinaguard_user;