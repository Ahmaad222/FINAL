-- TimescaleDB Extension and Hypertable Configuration
-- This script converts regular tables into hypertables for optimal time-series performance

-- Ensure TimescaleDB extension is created
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Convert threat_events to hypertable (time-series optimized for threat detection)
-- Using 'time' as the partition column. Must be in Primary Key.
SELECT create_hypertable('threat_events', 'time', if_not_exists => TRUE);

-- Convert sensor_health to hypertable (time-series optimized for sensor monitoring)
-- Using 'created_at' as the partition column. Must be in Primary Key.
SELECT create_hypertable('sensor_health', 'created_at', if_not_exists => TRUE);

-- Set up compression if not already enabled
-- Note: Compression and Continuous Aggregates have specific compatibility rules in different Timescale versions
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.compression_settings WHERE hypertable_name = 'threat_events') THEN
        ALTER TABLE threat_events SET (
            timescaledb.compress,
            timescaledb.compress_orderby = 'time DESC',
            timescaledb.compress_segmentby = 'threat_id'
        );
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.compression_settings WHERE hypertable_name = 'sensor_health') THEN
        ALTER TABLE sensor_health SET (
            timescaledb.compress,
            timescaledb.compress_orderby = 'created_at DESC',
            timescaledb.compress_segmentby = 'sensor_id'
        );
    END IF;
END $$;

-- Set up automatic data compression for old data (> 7 days)
SELECT add_compression_policy('threat_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('sensor_health', INTERVAL '7 days', if_not_exists => TRUE);

-- Set up retention policy (keep data for 90 days)
SELECT add_retention_policy('threat_events', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_retention_policy('sensor_health', INTERVAL '90 days', if_not_exists => TRUE);

-- Create useful indexes for time-series queries
-- Note: TimescaleDB automatically creates an index on the time column
CREATE INDEX IF NOT EXISTS idx_threat_events_threat_id ON threat_events (threat_id);
CREATE INDEX IF NOT EXISTS idx_sensor_health_sensor_id ON sensor_health (sensor_id);

-- Grant necessary permissions to application user
GRANT ALL ON ALL TABLES IN SCHEMA public TO zeinaguard_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO zeinaguard_user;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO zeinaguard_user;
