"""
Network Topology API Routes for ZeinaGuard Pro
Provides graph-compatible JSON data for network visualization
"""

from flask import Blueprint, jsonify, request
from models import Sensor, NetworkTopology
from topology_mock_data import get_mock_topology_data
from datetime import datetime

# Create blueprint
topology_bp = Blueprint('topology', __name__, url_prefix='/api/topology')


@topology_bp.route('', methods=['GET'])
def get_topology():
    """
    GET /api/topology
    Returns network topology graph with nodes and edges
    
    Prioritizes real data from NetworkTopology table, 
    falls back to mock data if no real data is found.
    """
    try:
        # Try to get real topology data from DB
        topologies = NetworkTopology.query.all()
        
        if not topologies:
            # Fallback to mock data for demo/empty state
            topology_data = get_mock_topology_data()
            return jsonify({
                'success': True,
                'data': topology_data,
                'message': 'Using simulated topology data (no real sensors detected)'
            }), 200
            
        # Transform real DB data to graph structure
        nodes = []
        edges = []
        shared_nodes = {}
        
        # Add sensors as nodes
        sensors = Sensor.query.all()
        for s in sensors:
            nodes.append({
                'id': f'sensor_{s.id}',
                'type': 'sensor',
                'label': s.name,
                'location': s.location,
                'mac_address': s.mac_address,
                'status': 'online' if s.is_active else 'offline'
            })
            
        # Track counts
        router_count = 0
        station_count = 0
        
        # Add discovered networks and devices from each sensor
        for topo in topologies:
            sensor_node_id = f'sensor_{topo.sensor_id}'
            
            # Networks (Routers/APs)
            if topo.discovered_networks:
                for net in topo.discovered_networks:
                    if not isinstance(net, dict): continue
                    
                    bssid = net.get('bssid')
                    if not bssid: continue
                    
                    node_id = f'router_{bssid.replace(":", "")}'
                    
                    # Deduplicate routers (same AP seen by multiple sensors)
                    existing_node = next((n for n in nodes if n['id'] == node_id), None)
                    if existing_node:
                        existing_node['is_shared'] = True
                        shared_nodes[node_id] = 'shared_router'
                    else:
                        nodes.append({
                            'id': node_id,
                            'type': 'router',
                            'label': net.get('ssid', 'Unknown SSID'),
                            'mac_address': bssid,
                            'channel': net.get('channel'),
                            'signal_strength': net.get('signal'),
                            'is_shared': False
                        })
                        router_count += 1
                        
                    # Add edge from sensor to router
                    edges.append({
                        'id': f'edge_{sensor_node_id}_{node_id}',
                        'source': sensor_node_id,
                        'target': node_id,
                        'type': 'detection',
                        'signal_strength': net.get('signal')
                    })
        
        return jsonify({
            'success': True,
            'data': {
                'nodes': nodes,
                'edges': edges,
                'metadata': {
                    'total_sensors': len(sensors),
                    'total_routers': router_count,
                    'total_stations': station_count,
                    'total_edges': len(edges),
                    'shared_nodes_count': len(shared_nodes),
                    'generated_at': datetime.utcnow().isoformat()
                }
            },
            'message': 'Real network topology retrieved successfully'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Failed to retrieve topology data'
        }), 500


@topology_bp.route('/sensors', methods=['GET'])
def get_topology_sensors():
    """Returns only sensor nodes from the topology"""
    try:
        sensors = Sensor.query.all()
        sensor_nodes = [{
            'id': f'sensor_{s.id}',
            'name': s.name,
            'location': s.location,
            'status': 'online' if s.is_active else 'offline'
        } for s in sensors]
        
        return jsonify({
            'success': True,
            'data': {'sensors': sensor_nodes, 'count': len(sensor_nodes)}
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
