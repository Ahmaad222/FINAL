"""
Migration script to fix database schema inconsistencies
Fixes types and adds missing columns/constraints
"""

import os
import sys
from sqlalchemy import text
from app import app, db

def fix_schema():
    with app.app_context():
        print("[MIGRATION] Starting database schema fix...")
        
        try:
            # 1. Fix Network Topology types (TEXT -> JSONB)
            print("[MIGRATION] Fixing network_topology types...")
            db.session.execute(text(
                "ALTER TABLE network_topology ALTER COLUMN discovered_networks TYPE JSONB USING discovered_networks::JSONB;"
            ))
            db.session.execute(text(
                "ALTER TABLE network_topology ALTER COLUMN discovered_devices TYPE JSONB USING discovered_devices::JSONB;"
            ))
            
            # 2. Fix Incident types (TEXT -> JSONB)
            print("[MIGRATION] Fixing incidents types...")
            db.session.execute(text(
                "ALTER TABLE incidents ALTER COLUMN threat_ids TYPE JSONB USING threat_ids::JSONB;"
            ))
            
            # 3. Fix Threat Event (Add ID column if missing)
            print("[MIGRATION] Checking threat_events ID column...")
            db.session.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='threat_events' AND column_name='id') THEN
                        ALTER TABLE threat_events ADD COLUMN id SERIAL PRIMARY KEY;
                    END IF;
                END $$;
            """))
            
            # 4. Fix Threat table (created_by nullable)
            print("[MIGRATION] Ensuring threats.created_by is nullable...")
            db.session.execute(text(
                "ALTER TABLE threats ALTER COLUMN created_by DROP NOT NULL;"
            ))
            
            # 5. Fix sensor_health (signal_strength might be NULL)
            print("[MIGRATION] Ensuring sensor_health constraints...")
            db.session.execute(text(
                "ALTER TABLE sensor_health ALTER COLUMN status TYPE VARCHAR(50);"
            ))
            
            # 6. Fix Audit Logs (changes JSONB)
            print("[MIGRATION] Fixing audit_logs types...")
            db.session.execute(text(
                "ALTER TABLE audit_logs ALTER COLUMN changes TYPE JSONB USING changes::JSONB;"
            ))
            
            db.session.commit()
            print("[MIGRATION] Database schema fix applied successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"[MIGRATION] Error applying schema fix: {str(e)}")
            # sys.exit(1)

if __name__ == "__main__":
    fix_schema()
