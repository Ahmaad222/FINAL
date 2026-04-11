"""
Script to verify data storage in PostgreSQL
Queries key tables and displays summary
"""

from app import app, db
from models import Threat, Sensor, NetworkTopology, User
from sqlalchemy import text

def verify_data():
    with app.app_context():
        print("\n=== ZEINAGUARD DATA VERIFICATION ===\n")
        
        # 1. Check Tables Existence
        print("[1] Checking table row counts:")
        try:
            threat_count = Threat.query.count()
            sensor_count = Sensor.query.count()
            topology_count = NetworkTopology.query.count()
            user_count = User.query.count()
            
            print(f"    - Threats:   {threat_count}")
            print(f"    - Sensors:   {sensor_count}")
            print(f"    - Topology:  {topology_count}")
            print(f"    - Users:     {user_count}")
        except Exception as e:
            print(f"    ❌ Error counting rows: {e}")
        
        # 2. Check Latest Threats
        print("\n[2] Latest 5 Threats:")
        try:
            latest_threats = Threat.query.order_by(Threat.created_at.desc()).limit(5).all()
            for t in latest_threats:
                print(f"    - [{t.created_at}] {t.threat_type} | SSID: {t.ssid} | Severity: {t.severity}")
            if not latest_threats:
                print("    (No threats found)")
        except Exception as e:
            print(f"    ❌ Error fetching threats: {e}")
            
        # 3. Check Network Topology
        print("\n[3] Network Topology Summary:")
        try:
            topologies = NetworkTopology.query.all()
            for topo in topologies:
                sensor = Sensor.query.get(topo.sensor_id)
                net_count = len(topo.discovered_networks) if topo.discovered_networks else 0
                print(f"    - Sensor: {sensor.name} | Discovered Networks: {net_count}")
            if not topologies:
                print("    (No topology data found)")
        except Exception as e:
            print(f"    ❌ Error fetching topology: {e}")

        # 4. Raw SQL Check (to verify types)
        print("\n[4] Database Schema Check (Types):")
        try:
            result = db.session.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'network_topology' 
                AND column_name IN ('discovered_networks', 'discovered_devices');
            """))
            for row in result:
                print(f"    - {row[0]}: {row[1]}")
        except Exception as e:
            print(f"    ❌ Error checking types: {e}")

        print("\n====================================\n")

if __name__ == "__main__":
    verify_data()
