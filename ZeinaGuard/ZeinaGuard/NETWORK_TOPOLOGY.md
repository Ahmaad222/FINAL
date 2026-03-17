# Network Topology Visualization Feature

## Overview

The Network Topology feature provides a real-time, interactive visualization of your wireless network infrastructure. It displays the relationships between Raspberry Pi sensors, access points, and connected devices in an easy-to-understand graph format.

## Features

### Visual Elements

- **Sensors** (Blue Hexagons): Raspberry Pi sensor nodes deployed in your network
- **Access Points** (Purple Circles): Wireless routers and APs detected by sensors
- **Stations** (Green Squares): Client devices (phones, laptops, tablets) connected to APs

### Shared Coverage Detection

Nodes that are visible/connected to **multiple sensors** are automatically highlighted with:
- ✨ **Gold Glowing Aura**: Indicates overlapping sensor coverage
- 🏷️ **SHARED Badge**: Clear visual indicator of multi-sensor visibility

This is useful for identifying:
- Areas with overlapping coverage (good redundancy)
- Devices roaming between APs (connected to multiple networks)
- Network blind spots (nodes visible to only one sensor)

### Security Threat Indicators

Nodes flagged as security threats display:
- 🚨 **Red Pulsing Aura**: CSS pulse animation for immediate attention
- ⚠️ **Threat Badge**: Alert displayed in details panel
- 🔴 **Red Icon**: Threat indicator on the node itself

## Interactive Features

### Node Selection & Details Panel

Click any node to open the **Details Sidebar** displaying:

- **Node Type**: Sensor, Router/AP, or Station
- **MAC Address**: Hardware identifier (copyable monospace format)
- **Signal Strength (RSSI)**: dBm value with visual strength indicator bar
  - Green: Excellent (-40 to -50 dBm)
  - Yellow: Good (-50 to -70 dBm)
  - Red: Poor (below -70 dBm)
- **Location**: Physical placement of sensors
- **SSID**: Network name for APs
- **Security Level**: WPA3, WPA2, WEP, or Open
- **Device Type**: Classification for stations
- **Status**: Online/Offline/Connected/Idle
- **Last Seen**: Timestamp of most recent activity

### Graph Navigation

- **Zoom**: Scroll wheel to zoom in/out
- **Pan**: Click and drag to move around the graph
- **Fit to View**: Double-click controls button or use fit-view control
- **Node Hover**: Hover over nodes to see scaling animation

## Understanding the Data

### Nodes & Edges

- **Nodes**: Individual network devices (sensors, APs, stations)
- **Edges**: Connections between nodes
  - **Blue Animated Edges**: Sensor detection connections (with signal strength)
  - **Purple Edges**: Station connections to APs

### Layout Algorithm

Nodes are positioned using a grid layout that automatically:
- Prevents overlapping
- Groups related nodes
- Maintains readable distances

Future: Force-directed layout for more natural arrangements

## API Integration

The feature fetches data from `/api/topology` endpoint with the following structure:

```json
{
  "nodes": [
    {
      "id": "sensor_1",
      "type": "sensor",
      "label": "Raspberry Pi 1",
      "location": "Office Floor 1",
      "mac_address": "B8:27:EB:XX:XX:XX",
      "status": "online",
      "signal_strength": -55,
      "is_shared": true,
      "is_suspicious": false
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "sensor_1",
      "target": "router_1",
      "type": "detection",
      "signal_strength": -55
    }
  ],
  "metadata": {
    "total_nodes": 12,
    "total_edges": 14,
    "shared_nodes_count": 9
  }
}
```

## UI/UX Design

### Dark Theme

All components use the dark slate-900 theme for consistency with the ZeinaGuard dashboard:
- Slate-900: Primary background
- Slate-800: Secondary background / panels
- Slate-700: Borders and subtle elements

### Color Coding

- **Blue**: Sensor nodes (primary color)
- **Purple**: Access point/router nodes
- **Green**: Station/device nodes
- **Yellow/Gold**: Shared coverage indicator
- **Red**: Security threat indicator

### Responsive Layout

- Graph container is full-screen and responsive
- Details panel slides in from the right (320px width)
- Controls positioned bottom-left with dark theme
- Mobile-friendly with touch-optimized interactions

## Shared Visibility Logic

### How It Works

The backend analyzes network data to identify:

1. **Shared Routers**: APs detected by 2+ sensors
   - Indicates overlapping coverage area
   - Good for redundancy
   - May indicate AP in central location

2. **Shared Stations**: Devices connected to 2+ APs
   - Indicates device roaming
   - Good for mobility support
   - May indicate handoff issues if frequent

3. **Coverage Gaps**: Nodes visible to only 1 sensor
   - Indicates potential blind spot
   - May require additional sensor deployment

### Visual Indicators

```
Shared Node = is_shared: true
    ↓
CSS Class: node-shared
    ↓
Drop-Shadow Filter + Pulse Animation (Gold Glow)
    ↓
"SHARED" Badge on node
```

## Real-time Pulse Animation

### Shared Coverage Pulse

Gentle gold pulse animation indicates consistently shared visibility:
```css
@keyframes shared-pulse {
  0%: drop-shadow(0 0 8px rgba(234, 179, 8, 0.6))
  50%: drop-shadow(0 0 16px rgba(234, 179, 8, 1))  /* Peak brightness */
  100%: drop-shadow(0 0 8px rgba(234, 179, 8, 0.6))
}
Duration: 2s ease-in-out (smooth breathing effect)
```

### Threat Alert Pulse

Urgent red pulse for security threats:
```css
@keyframes threat-pulse {
  0%: drop-shadow(0 0 0px transparent)
  50%: drop-shadow(0 0 20px rgba(239, 68, 68, 1))  /* Peak intensity */
  100%: drop-shadow(0 0 0px transparent)
}
Duration: 1s ease-in-out (urgent, attention-grabbing)
```

## Best Practices

### Interpreting the Network

1. **Overlapping Coverage**: Shared nodes (gold glow) indicate areas with sensor redundancy
2. **Security Monitoring**: Watch for threat pulse (red) on any nodes
3. **Device Movement**: Shared stations indicate roaming devices
4. **Coverage Planning**: Unshared nodes may need additional sensors

### Network Optimization

- Use shared node information to plan sensor placement
- Identify devices with connectivity issues (low RSSI)
- Monitor threat indicators for security anomalies
- Track roaming patterns for mobility optimization

## Troubleshooting

### Graph Not Loading

- Verify backend API is running (`/api/topology`)
- Check browser console for CORS or network errors
- Ensure topology mock data is accessible

### Shared Nodes Not Showing

- Check mock data generation includes overlapping coverage
- Verify `is_shared` flag is set in API response
- Inspect browser DevTools to see CSS classes applied

### Pulse Animation Not Working

- Ensure `topology.css` is imported in network-graph.tsx
- Check browser support for CSS filter drop-shadow
- Verify `node-shared` and `node-threat` classes are applied

## Future Enhancements

- [ ] Force-directed auto-layout for natural positioning
- [ ] Real-time WebSocket updates
- [ ] Node filtering by type
- [ ] Export topology as image/PDF
- [ ] Topology change alerts
- [ ] Historical topology tracking
- [ ] Multi-layer network view (2.4GHz vs 5GHz)
- [ ] Custom node positioning and saved layouts

## Technical Stack

- **Frontend**: React, Next.js, ReactFlow, TailwindCSS
- **Backend**: Flask, Python
- **Visualization**: ReactFlow library with custom node components
- **Styling**: TailwindCSS + CSS animations
- **Real-time**: WebSocket-ready (not yet implemented)

## Files

### Frontend
- `app/topology/page.tsx` - Main topology page
- `app/topology/layout.tsx` - Metadata
- `components/topology/network-graph.tsx` - Main graph component
- `components/topology/topology.css` - Animations and styling
- `components/topology/nodes/sensor-node.tsx` - Sensor node component
- `components/topology/nodes/router-node.tsx` - Router node component
- `components/topology/nodes/station-node.tsx` - Station node component

### Backend
- `backend/topology_mock_data.py` - Mock data generator
- `backend/routes_topology.py` - API endpoints

## Support

For questions or issues, refer to the ZeinaGuard main documentation or contact the development team.
