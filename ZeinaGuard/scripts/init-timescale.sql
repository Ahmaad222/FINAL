-- TimescaleDB Extension and Hypertable Configuration
-- This script converts regular tables into hypertables for optimal time-series performance

-- Ensure TimescaleDB extension is created
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Convert threat_events to hypertable (time-series optimized for threat detection)
SELECT create_hypertable('threat_events', 'time', if_not_exists => TRUE);

-- Convert sensor_health to hypertable (time-series optimized for sensor monitoring)
SELECT create_hypertable('sensor_health', 'created_at', if_not_exists => TRUE);

-- Set up compression if not already enabled
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.compression_settings WHERE hypertable_name = 'threat_events') THEN
        ALTER TABLE threat_events SET (
            timescaledb.compress,
            timescaledb.compress_orderby = 'threat_id, time DESC',
            timescaledb.compress_segmentby = 'threat_id'
        );
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.compression_settings WHERE hypertable_name = 'sensor_health') THEN
        ALTER TABLE sensor_health SET (
            timescaledb.compress,
            timescaledb.compress_orderby = 'sensor_id, created_at DESC',
            timescaledb.compress_segmentby = 'sensor_id'
        );
    END IF;
END $$;

-- Set up automatic data compression for old data (> 7 days)
SELECT add_compression_policy('threat_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('sensor_health', INTERVAL '7 days', if_not_exists => TRUE);

-- Create continuous aggregates for fast analytics queries
-- Daily threat summary (updates automatically)
CREATE MATERIALIZED VIEW IF NOT EXISTS threat_events_daily AS
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

-- Hourly threat summary (for dashboards)
CREATE MATERIALIZED VIEW IF NOT EXISTS threat_events_hourly AS
SELECT
    time_bucket('1 hour', time) as bucket,
    threat_id,
    sensor_id,
    COUNT(*) as event_count,
    AVG(packet_count) as avg_packets
FROM threat_events
GROUP BY bucket, threat_id, sensor_id;

-- Sensor health daily summary
CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_health_daily AS
SELECT
    time_bucket('1 day', created_at) as bucket,
    sensor_id,
    AVG(CAST(signal_strength AS FLOAT)) as avg_signal,
    AVG(cpu_usage) as avg_cpu,
    AVG(memory_usage) as avg_memory,
    MAX(uptime) as max_uptime
FROM sensor_health
GROUP BY bucket, sensor_id;

-- Create refresh policies for continuous aggregates
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

-- Create retention policy (keep data for 90 days)
SELECT add_retention_policy('threat_events', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_retention_policy('sensor_health', INTERVAL '90 days', if_not_exists => TRUE);

-- Create useful indexes for time-series queries
CREATE INDEX IF NOT EXISTS threat_events_threat_time ON threat_events (threat_id, time DESC);
CREATE INDEX IF NOT EXISTS threat_events_sensor_time ON threat_events (sensor_id, time DESC);
CREATE INDEX IF NOT EXISTS sensor_health_sensor_time ON sensor_health (sensor_id, created_at DESC);

-- Grant necessary permissions to application user
GRANT ALL ON ALL TABLES IN SCHEMA public TO zeinaguard_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO zeinaguard_user;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO zeinaguard_user;
