# Phase 5: Command Palette & Advanced Features

## Overview

Phase 5 implements premium UX features and advanced security management interfaces. This phase adds the Command Palette (Cmd+K) and complete WIPS feature set.

## Key Features Implemented

### 1. Command Palette (Cmd+K)
- **Quick Search**: Type to search all commands
- **Fuzzy Matching**: Natural language search
- **Categories**: Navigation, Testing, Actions, Settings
- **Shortcuts**: Keyboard navigation with arrow keys
- **Demo Commands**:
  - Navigate to any page
  - Simulate threats
  - Block MAC addresses
  - Create alert rules
  - View sensor status

**Usage:**
```
Press Cmd+K (Mac) or Ctrl+K (Windows/Linux) to open
Type to search: e.g., "block 00:1A:2B"
Press Enter to execute
```

### 2. Sensor Management Page (`/sensors`)
- **Heartbeat Monitoring**: Real-time sensor status
- **Signal Strength Visualization**: dBm measurements with sparklines
- **Uptime Tracking**: 24-hour uptime percentage
- **Coverage Areas**: Physical location and coverage zones
- **Status Indicators**: Online/Offline/Degraded states
- **Auto-refresh**: Updates every 5 seconds

**Features:**
- Grid view of all sensors
- Signal quality indicators (Excellent/Good/Fair/Poor)
- Packet count tracking
- Last seen timestamps

### 3. Alert Rules Page (`/alerts`)
- **Create Alert Rules**: Define custom detection rules
- **Severity Levels**: Critical, High, Medium, Low
- **Trigger Conditions**: Flexible condition syntax
- **Rule Management**: Enable/disable rules
- **Active Monitoring**: Only active rules trigger alerts

**Use Cases:**
- Block rogue APs automatically
- Alert on deauthentication attacks
- Detect spectrum usage anomalies
- Monitor sensor health

### 4. Incident Response Page (`/incidents`)
- **Track Incidents**: Central incident database
- **Status Tracking**: Open → In Progress → Resolved
- **Assignment**: Route incidents to analysts
- **Time Tracking**: Created and updated timestamps
- **Severity Levels**: Color-coded severity
- **Filtering**: View by status

**Features:**
- Chronological incident list
- Quick status updates
- Assignment tracking
- Severity prioritization

### 5. Navigation & Layout
- **Sidebar Navigation**: Always-visible menu
- **Active Indicators**: Current page highlighting
- **User Info**: Display logged-in user
- **Quick Logout**: Logout button in footer
- **App Layout Wrapper**: Consistent layout across all pages

## Architecture

```
Components
├── command-palette.tsx          # Cmd+K command palette UI
├── layout/
│   ├── sidebar.tsx             # Navigation sidebar
│   └── app-layout.tsx          # Main layout wrapper
└── dashboard/
    ├── metrics-card.tsx        # Reusable metric card
    └── threat-timeline-chart.tsx # Recharts visualization

Pages
├── /sensors                     # Sensor management & heartbeat monitor
├── /alerts                      # Alert rules configuration
├── /incidents                   # Incident response dashboard
└── (All wrapped with AppLayout)

Hooks
└── use-command-palette.ts      # Command palette state & logic
```

## Command Palette Implementation

### Available Commands

**Navigation Commands:**
- `Dashboard` - Go to main dashboard
- `Threats` - View threat feed
- `Sensors` - Manage sensors
- `Alerts` - Configure alert rules
- `Incidents` - View incidents

**Testing Commands:**
- `Simulate Threat` - Demo threat detection
- `Generate Report` - Export PDF report
- `Run Health Check` - System diagnostics

**Actions:**
- `Block MAC 00:1A:...` - Add to blocklist
- `Create Rule` - New alert rule
- `Assign Incident` - Route to analyst

**Settings:**
- `View Settings` - System configuration
- `User Management` - Manage accounts
- `API Keys` - Manage integrations

### Hook Usage

```typescript
import { useCommandPalette } from '@/hooks/use-command-palette';

function MyComponent() {
  const { isOpen, groupedCommands, executeCommand } = useCommandPalette();
  // Execute commands programmatically
}
```

## Data Flow

```
User Input (Cmd+K)
    ↓
useCommandPalette Hook
    ↓
Command Palette UI (Renders commands)
    ↓
Command Execution
    ↓
Navigation / API Call / State Update
```

## Database Integration

All pages fetch data from Flask API endpoints:

```
GET /api/sensors           → Sensor list with status
GET /api/alerts            → Alert rules
GET /api/incidents         → Incidents list
POST /api/alerts           → Create new rule
POST /api/incidents/:id    → Update incident
```

## UI/UX Details

### Color Scheme
- **Command Categories**: Blue (Navigation), Orange (Testing), Purple (Actions), Gray (Settings)
- **Sensor Status**: Green (Online), Red (Offline), Yellow (Degraded)
- **Severity Levels**: Red (Critical), Orange (High), Yellow (Medium), Blue (Low)

### Animations
- Smooth transitions on all interactive elements
- Hover states for better feedback
- Auto-scroll to selected command
- Fade-in animations for modal

## Performance Considerations

1. **Sensor Page**: Refreshes every 5 seconds (configurable)
2. **Command Palette**: Debounced search (300ms)
3. **Sidebar**: Memoized to prevent re-renders
4. **Lazy Loading**: Pages loaded on-demand

## Security Notes

- Command Palette: All commands require JWT authentication
- API Endpoints: Protected with @jwt_required() decorator
- MAC Address Blocking: Requires admin role
- Incident Assignment: Role-based access control

## Testing Phase 5

1. **Open Dashboard**: Navigate to /dashboard
2. **Open Command Palette**: Press Cmd+K
3. **Test Navigation**: Search "threats" → Press Enter
4. **Test Demo**: Search "simulate" → Press Enter (simulates threat)
5. **Check Sensors**: Go to /sensors → See heartbeat monitors
6. **Configure Alerts**: Go to /alerts → Click "New Rule"
7. **Track Incidents**: Go to /incidents → Filter by status

## Next Steps: Phase 6

Phase 6 (Polish & Deployment) will:
- Add performance optimizations
- Implement security hardening
- Add mobile responsiveness
- Prepare for production deployment
- Create deployment documentation
