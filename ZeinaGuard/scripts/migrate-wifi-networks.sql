-- ZeinaGuard Pro - WiFi Networks Migration Script
-- Run this on existing databases to add the new optimized tables
-- Usage: psql -U zeinaguard_user -d zeinaguard_db -f migrate-wifi-networks.sql

BEGIN;

-- =========================================================
-- 1. Create wifi_networks table (if not exists)
-- =========================================================

CREATE TABLE IF NOT EXISTS wifi_networks (
    id SERIAL PRIMARY KEY,
    sensor_id INTEGER NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,

    -- Network identification
    ssid VARCHAR(255) NOT NULL,
    bssid VARCHAR(17) NOT NULL,

    -- Network properties
    channel INTEGER,
    frequency INTEGER,
    signal_strength INTEGER,
    encryption VARCHAR(50),
    auth_type VARCHAR(50),
    wps_info JSONB,

    -- Additional metadata
    manufacturer VARCHAR(255),
    device_type VARCHAR(50) DEFAULT 'AP',
    uptime_seconds INTEGER,

    -- Deduplication counters
    seen_count INTEGER DEFAULT 1,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- Raw data for debugging
    raw_beacon TEXT,

    -- Constraints
    CONSTRAINT uq_sensor_bssid UNIQUE (sensor_id, bssid)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_wifi_networks_ssid ON wifi_networks(ssid);
CREATE INDEX IF NOT EXISTS idx_wifi_networks_bssid ON wifi_networks(bssid);
CREATE INDEX IF NOT EXISTS idx_wifi_networks_sensor_id ON wifi_networks(sensor_id);
CREATE INDEX IF NOT EXISTS idx_wifi_networks_sensor_lastseen ON wifi_networks(sensor_id, last_seen);
CREATE INDEX IF NOT EXISTS idx_wifi_networks_signal ON wifi_networks(signal_strength);

-- =========================================================
-- 2. Create network_scan_events table (if not exists)
-- =========================================================

CREATE TABLE IF NOT EXISTS network_scan_events (
    id SERIAL PRIMARY KEY,
    sensor_id INTEGER NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    network_id INTEGER REFERENCES wifi_networks(id) ON DELETE CASCADE,

    -- Event data
    event_type VARCHAR(50) DEFAULT 'SCAN',
    severity VARCHAR(50) DEFAULT 'INFO',
    risk_score FLOAT,

    -- Snapshot of network state
    signal_strength INTEGER,
    channel INTEGER,

    -- Additional context
    reasons JSONB,
    metadata JSONB,

    -- Timestamp
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- Cleanup marker
    is_purged BOOLEAN DEFAULT FALSE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_scan_events_sensor_time ON network_scan_events(sensor_id, scanned_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_events_network ON network_scan_events(network_id);
CREATE INDEX IF NOT EXISTS idx_scan_events_severity ON network_scan_events(severity);
CREATE INDEX IF NOT EXISTS idx_scan_events_purged ON network_scan_events(is_purged);
CREATE INDEX IF NOT EXISTS idx_scan_events_scanned_at ON network_scan_events(scanned_at DESC);

-- =========================================================
-- 3. Create helper function for cleanup
-- =========================================================

CREATE OR REPLACE FUNCTION cleanup_old_scan_events(retention_hours INTEGER DEFAULT 720)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
    cutoff_time TIMESTAMP;
BEGIN
    cutoff_time := CURRENT_TIMESTAMP - (retention_hours || ' hours')::INTERVAL;

    DELETE FROM network_scan_events
    WHERE scanned_at < cutoff_time;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- =========================================================
-- 4. Create view for current network state
-- =========================================================

CREATE OR REPLACE VIEW v_current_networks AS
SELECT
    wn.id,
    wn.sensor_id,
    s.name AS sensor_name,
    wn.ssid,
    wn.bssid,
    wn.channel,
    wn.frequency,
    wn.signal_strength,
    wn.encryption,
    wn.auth_type,
    wn.manufacturer,
    wn.seen_count,
    wn.first_seen,
    wn.last_seen,
    wn.uptime_seconds,
    CASE
        WHEN wn.last_seen < CURRENT_TIMESTAMP - INTERVAL '5 minutes' THEN 'offline'
        ELSE 'active'
    END AS status
FROM wifi_networks wn
LEFT JOIN sensors s ON wn.sensor_id = s.id
ORDER BY wn.last_seen DESC;

-- =========================================================
-- 5. Create view for recent threats
-- =========================================================

CREATE OR REPLACE VIEW v_recent_threats AS
SELECT
    t.id,
    t.threat_type,
    t.severity,
    t.source_mac,
    t.target_mac,
    t.ssid,
    s.name AS sensor_name,
    t.description,
    t.is_resolved,
    t.created_at
FROM threats t
LEFT JOIN sensors s ON t.detected_by = s.id
WHERE t.created_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
ORDER BY t.created_at DESC;

-- =========================================================
-- 6. Migrate existing data from network_topology (if any)
-- =========================================================

-- Migrate discovered networks from network_topology JSON to wifi_networks
INSERT INTO wifi_networks (sensor_id, ssid, bssid, first_seen, last_seen, seen_count)
SELECT DISTINCT ON (nt.sensor_id, net.bssid)
    nt.sensor_id,
    net.ssid,
    net.bssid,
    COALESCE(TO_TIMESTAMP(net.last_seen, 'YYYY-MM-DD"T"HH24:MI:SS.MS'), CURRENT_TIMESTAMP) AS first_seen,
    COALESCE(TO_TIMESTAMP(net.last_seen, 'YYYY-MM-DD"T"HH24:MI:SS.MS'), CURRENT_TIMESTAMP) AS last_seen,
    1 AS seen_count
FROM network_topology nt,
     LATERAL jsonb_array_elements(
         COALESCE(nt.discovered_networks, '[]'::jsonb)
     ) AS net(bssid, ssid, last_seen)
WHERE net.bssid IS NOT NULL
ON CONFLICT (sensor_id, bssid) DO UPDATE SET
    last_seen = EXCLUDED.last_seen,
    ssid = EXCLUDED.ssid;

-- =========================================================
-- 7. Grant permissions
-- =========================================================

GRANT ALL ON wifi_networks TO zeinaguard_user;
GRANT ALL ON network_scan_events TO zeinaguard_user;
GRANT ALL ON SEQUENCE wifi_networks_id_seq TO zeinaguard_user;
GRANT ALL ON SEQUENCE network_scan_events_id_seq TO zeinaguard_user;
GRANT EXECUTE ON FUNCTION cleanup_old_scan_events TO zeinaguard_user;

-- =========================================================
-- Migration complete
-- =========================================================

COMMIT;

-- Display summary
SELECT 'Migration completed successfully!' AS status;
SELECT COUNT(*) AS wifi_networks_count FROM wifi_networks;
SELECT COUNT(*) AS scan_events_count FROM network_scan_events;
