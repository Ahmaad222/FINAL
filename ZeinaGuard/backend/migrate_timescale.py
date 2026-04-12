"""
Migration script for TimescaleDB compatibility
Converts TIMESTAMP to TIMESTAMPTZ and fixes Primary Keys for Hypertables
"""

from app import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        print("[MIGRATION] Starting TimescaleDB compatibility migration...")
        
        try:
            # 1. Convert all TIMESTAMP columns to TIMESTAMPTZ
            tables_to_fix = [
                ('users', ['last_login', 'created_at', 'updated_at']),
                ('roles', ['created_at']),
                ('permissions', ['created_at']),
                ('sensors', ['created_at', 'updated_at']),
                ('sensor_health', ['last_heartbeat', 'created_at']),
                ('network_topology', ['created_at', 'updated_at']),
                ('threats', ['created_at', 'updated_at']),
                ('threat_events', ['time', 'created_at']),
                ('alert_rules', ['created_at', 'updated_at']),
                ('alerts', ['acknowledged_at', 'created_at']),
                ('incidents', ['created_at', 'updated_at', 'resolved_at']),
                ('incident_events', ['created_at']),
                ('reports', ['created_at']),
                ('audit_logs', ['created_at']),
                ('blocked_devices', ['created_at', 'expires_at']),
                ('topology_sensors', ['last_seen', 'created_at', 'updated_at']),
                ('topology_access_points', ['last_seen', 'created_at', 'updated_at']),
                ('topology_stations', ['last_seen', 'created_at', 'updated_at']),
                ('topology_connections', ['created_at', 'updated_at']),
            ]
            
            for table, columns in tables_to_fix:
                for col in columns:
                    print(f"    - Converting {table}.{col} to TIMESTAMPTZ")
                    db.session.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMPTZ USING {col} AT TIME ZONE 'UTC';"))
            
            # 2. Fix Primary Keys for tables intended to be Hypertables
            print("[MIGRATION] Fixing Primary Keys for hypertables...")
            
            # For sensor_health
            print("    - Fixing sensor_health PK")
            db.session.execute(text("ALTER TABLE sensor_health DROP CONSTRAINT IF EXISTS sensor_health_pkey CASCADE;"))
            db.session.execute(text("ALTER TABLE sensor_health ADD PRIMARY KEY (id, created_at);"))
            
            # For threat_events
            print("    - Fixing threat_events PK")
            db.session.execute(text("ALTER TABLE threat_events DROP CONSTRAINT IF EXISTS threat_events_pkey CASCADE;"))
            db.session.execute(text("ALTER TABLE threat_events ADD PRIMARY KEY (id, time);"))
            
            # 3. Create Hypertables if not exists
            print("[MIGRATION] Creating hypertables...")
            db.session.execute(text("SELECT create_hypertable('sensor_health', 'created_at', if_not_exists => TRUE);"))
            db.session.execute(text("SELECT create_hypertable('threat_events', 'time', if_not_exists => TRUE);"))
            
            db.session.commit()
            print("[MIGRATION] TimescaleDB compatibility migration complete!")
            
        except Exception as e:
            db.session.rollback()
            print(f"[MIGRATION] Error during migration: {str(e)}")

if __name__ == "__main__":
    migrate()
