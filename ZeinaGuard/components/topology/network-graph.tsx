'use client';

import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react';
import ReactFlow, {
  Background,
  Controls,
  Edge,
  MarkerType,
  MiniMap,
  Node,
  Position,
  ReactFlowInstance,
  useEdgesState,
  useNodesState,
} from 'reactflow';
import { io, Socket } from 'socket.io-client';
import { AlertTriangle, Shield, Wifi, WifiOff, Zap } from 'lucide-react';
import { toast } from 'sonner';
import 'reactflow/dist/style.css';
import './topology.css';


type Classification = 'rogue' | 'suspicious' | 'legit';

interface ClientSnapshot {
  mac: string;
  type?: string | null;
}

interface NetworkSnapshotItem {
  sensor_id: number | null;
  bssid: string;
  ssid: string;
  signal: number | null;
  classification: Classification;
  last_seen: string;
  clients: ClientSnapshot[];
}

interface GraphNodeData {
  kind: 'network' | 'device';
  label: ReactNode;
  displayLabel: string;
  bssid?: string;
  mac?: string;
  ssid?: string;
  signal?: number | null;
  classification?: Classification;
  last_seen?: string;
  sensor_id?: number | null;
  clients?: ClientSnapshot[];
  deviceType?: string;
}

interface AttackCommandAckEvent {
  status?: 'ok' | 'error' | string;
  sensor_id?: number | null;
  bssid?: string | null;
  message?: string | null;
}

interface AttackAckEvent {
  status?: 'executed' | 'failed' | string;
  sensor_id?: number | null;
  bssid?: string | null;
  message?: string | null;
}


const SOCKET_URL = (
  process.env.NEXT_PUBLIC_SOCKET_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  'http://localhost:5000'
).replace(/\/$/, '');


function normalizeClassification(value: unknown): Classification {
  const classification = String(value || 'legit').trim().toLowerCase();
  if (classification === 'rogue' || classification === 'suspicious') {
    return classification;
  }
  return 'legit';
}


function normalizeLastSeen(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    const timestamp = value > 1_000_000_000_000 ? value : value * 1000;
    return new Date(timestamp).toISOString();
  }

  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (/^\d+$/.test(trimmed)) {
      const numericValue = Number(trimmed);
      const timestamp = numericValue > 1_000_000_000_000 ? numericValue : numericValue * 1000;
      return new Date(timestamp).toISOString();
    }

    const parsed = new Date(trimmed);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString();
    }
  }

  return new Date().toISOString();
}


function normalizeClient(client: ClientSnapshot): ClientSnapshot | null {
  const mac = String(client?.mac || '').trim().toUpperCase();
  if (!mac) {
    return null;
  }

  return {
    mac,
    type: String(client?.type || 'device').trim().toLowerCase() || 'device',
  };
}


function normalizeSnapshot(payload: unknown): NetworkSnapshotItem[] {
  const rawSnapshot = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object' && Array.isArray((payload as { data?: unknown[] }).data)
      ? (payload as { data: unknown[] }).data
      : null;

  if (!rawSnapshot) {
    return [];
  }

  return rawSnapshot
    .map((item) => {
      if (!item || typeof item !== 'object') {
        return null;
      }

      const network = item as Record<string, unknown>;
      const bssid = String(network.bssid || '').trim().toUpperCase();
      if (!bssid) {
        return null;
      }

      const clients = Array.isArray(network.clients)
        ? network.clients
            .map((client) => normalizeClient(client as ClientSnapshot))
            .filter((client): client is ClientSnapshot => Boolean(client))
        : [];

      return {
        sensor_id: typeof network.sensor_id === 'number' ? network.sensor_id : Number(network.sensor_id || 0) || null,
        bssid,
        ssid: String(network.ssid || 'Hidden').trim() || 'Hidden',
        signal: network.signal == null ? null : Number(network.signal),
        classification: normalizeClassification(network.classification),
        last_seen: normalizeLastSeen(network.last_seen),
        clients,
      };
    })
    .filter((network): network is NetworkSnapshotItem => Boolean(network));
}


function getNodeStyle(classification: Classification) {
  switch (classification) {
    case 'rogue':
      return { border: '2px solid #ef4444', boxShadow: '0 0 10px rgba(239, 68, 68, 0.9)' };
    case 'suspicious':
      return { border: '2px solid #f59e0b', boxShadow: '0 0 10px rgba(245, 158, 11, 0.35)' };
    default:
      return { border: '2px solid #22c55e', boxShadow: '0 0 10px rgba(34, 197, 94, 0.25)' };
  }
}


function getEdgeStyle(classification: Classification) {
  switch (classification) {
    case 'rogue':
      return '#ef4444';
    case 'suspicious':
      return '#f59e0b';
    default:
      return '#22c55e';
  }
}


function relativeLastSeen(lastSeen?: string) {
  if (!lastSeen) {
    return 'unknown';
  }

  const deltaSeconds = Math.max(0, Math.floor((Date.now() - new Date(lastSeen).getTime()) / 1000));
  if (deltaSeconds < 2) {
    return 'now';
  }
  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`;
  }
  if (deltaSeconds < 3600) {
    return `${Math.floor(deltaSeconds / 60)}m ago`;
  }
  return `${Math.floor(deltaSeconds / 3600)}h ago`;
}


function buildGraph(snapshot: NetworkSnapshotItem[]): { nodes: Node<GraphNodeData>[]; edges: Edge[] } {
  const nodes: Node<GraphNodeData>[] = [];
  const edges: Edge[] = [];
  const deviceNodes = new Map<string, Node<GraphNodeData>>();

  const columnCount = Math.max(1, Math.ceil(Math.sqrt(Math.max(snapshot.length, 1))));
  const cellWidth = 320;
  const cellHeight = 250;
  const startX = 120;
  const startY = 110;

  snapshot.forEach((network, index) => {
    const classification = normalizeClassification(network.classification);
    const column = index % columnCount;
    const row = Math.floor(index / columnCount);
    const networkX = startX + (column * cellWidth);
    const networkY = startY + (row * cellHeight);

    nodes.push({
      id: network.bssid,
      position: { x: networkX, y: networkY },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
      draggable: false,
      data: {
        kind: 'network',
        label: (
          <div className="space-y-1">
            <div className="truncate text-sm font-semibold text-slate-50">{network.ssid || 'Hidden'}</div>
            <div className="truncate font-mono text-[10px] text-slate-400">{network.bssid}</div>
            <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.2em] text-slate-300">
              <span>{classification}</span>
              <span>{network.signal ?? 'N/A'} dBm</span>
            </div>
          </div>
        ),
        displayLabel: network.ssid || 'Hidden',
        bssid: network.bssid,
        ssid: network.ssid || 'Hidden',
        signal: network.signal ?? null,
        classification,
        last_seen: typeof network.last_seen === 'string' ? network.last_seen : normalizeLastSeen(network.last_seen),
        sensor_id: network.sensor_id ?? null,
        clients: network.clients || [],
      },
      style: {
        width: 184,
        minHeight: 74,
        background: '#020617',
        color: '#f8fafc',
        borderRadius: 18,
        padding: '14px 16px',
        fontSize: 12,
        fontWeight: 600,
        textAlign: 'left',
        ...getNodeStyle(classification),
      },
    });

    const clients = network.clients || [];
    const angleStep = clients.length > 0 ? (Math.PI * 2) / clients.length : 0;

    clients.forEach((client, clientIndex) => {
      if (!client.mac) {
        return;
      }

      if (!deviceNodes.has(client.mac)) {
        const angle = (angleStep * clientIndex) - (Math.PI / 2);
        const deviceX = networkX + (Math.cos(angle) * 150);
        const deviceY = networkY + 110 + (Math.sin(angle) * 95);

        deviceNodes.set(client.mac, {
          id: client.mac,
          position: { x: deviceX, y: deviceY },
          draggable: false,
          data: {
            kind: 'device',
            label: (
              <div className="space-y-1">
                <div className="truncate font-mono text-[11px] text-slate-100">{client.mac}</div>
                <div className="text-[10px] uppercase tracking-[0.2em] text-slate-400">{client.type || 'device'}</div>
              </div>
            ),
            displayLabel: client.mac,
            mac: client.mac,
            deviceType: client.type || 'device',
          },
          style: {
            width: 176,
            minHeight: 58,
            background: '#0f172a',
            color: '#cbd5e1',
            border: '1px solid #334155',
            borderRadius: 14,
            padding: '10px 12px',
            fontSize: 11,
            fontWeight: 500,
            textAlign: 'left',
            boxShadow: '0 0 12px rgba(15, 23, 42, 0.35)',
          },
        });
      }

      edges.push({
        id: `${network.bssid}-${client.mac}`,
        source: network.bssid,
        target: client.mac,
        animated: classification === 'rogue',
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 18,
          height: 18,
          color: getEdgeStyle(classification),
        },
        style: {
          stroke: getEdgeStyle(classification),
          strokeWidth: classification === 'rogue' ? 2.4 : 1.8,
        },
      });
    });
  });

  nodes.push(...deviceNodes.values());
  return { nodes, edges };
}


export function NetworkGraph() {
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNodeData | null>(null);

  const socketRef = useRef<Socket | null>(null);
  const flowRef = useRef<ReactFlowInstance | null>(null);

  useEffect(() => {
    const socket = io(SOCKET_URL, {
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: Infinity,
      timeout: 10000,
      transports: ['websocket', 'polling'],
    });

    socketRef.current = socket;

    socket.on('connect', () => {
      setConnected(true);
      setError(null);
    });

    socket.on('disconnect', () => {
      setConnected(false);
    });

    socket.on('connect_error', (connectError: Error) => {
      setConnected(false);
      setLoading(false);
      setError(connectError.message || 'Unable to connect to realtime backend');
    });

    socket.on('networks_snapshot', (payload: unknown) => {
      const snapshot = normalizeSnapshot(payload);
      const nextGraph = buildGraph(snapshot);

      setNodes(nextGraph.nodes);
      setEdges(nextGraph.edges);
      setLoading(false);
      setError(null);

      window.requestAnimationFrame(() => {
        flowRef.current?.fitView({ padding: 0.2, duration: 350 });
      });
    });

    socket.on('attack_command_ack', (event: AttackCommandAckEvent) => {
      if (event.status === 'ok') {
        toast.success('Attack dispatched', {
          description: event.bssid || 'Containment request accepted',
        });
        return;
      }

      toast.error('Attack rejected', {
        description: event.message || event.bssid || 'Backend rejected the attack command',
      });
    });

    socket.on('attack_ack', (event: AttackAckEvent) => {
      if (event.status === 'executed') {
        toast.success('Attack executed', {
          description: event.bssid || 'Sensor confirmed containment',
        });
        return;
      }

      toast.error('Attack failed', {
        description: event.message || event.bssid || 'Sensor reported a containment failure',
      });
    });

    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, [setEdges, setNodes]);

  const handleNodeClick = async (_event: ReactMouseEvent, node: Node<GraphNodeData>) => {
    setSelectedNode(node.data);

    if (node.data.kind !== 'network') {
      return;
    }

    const sensorId = node.data.sensor_id;
    if (!sensorId) {
      toast.error('Attack unavailable', {
        description: 'This network is missing its sensor mapping',
      });
      return;
    }

    if (!socketRef.current?.connected) {
      toast.error('Realtime backend offline', {
        description: 'Reconnect to dispatch an attack command',
      });
      return;
    }

    socketRef.current.emit('attack_command', {
      sensor_id: sensorId,
      bssid: node.id,
    });

    toast.message('Attack requested', {
      description: `${node.data.ssid || node.data.label} (${node.id})`,
    });
  };

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-slate-950">
        <div className="text-center">
          <div className="mx-auto mb-4 h-12 w-12 rounded-full border-4 border-cyan-500 border-t-transparent animate-spin" />
          <p className="text-slate-300">Waiting for live network snapshots...</p>
        </div>
      </div>
    );
  }

  if (error && nodes.length === 0) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-slate-950">
        <div className="max-w-md rounded-2xl border border-red-800 bg-slate-900 p-8 text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full border border-red-700 bg-red-950/40">
            <WifiOff className="h-7 w-7 text-red-400" />
          </div>
          <h2 className="mb-2 text-2xl font-semibold text-white">Realtime connection failed</h2>
          <p className="mb-4 text-sm text-slate-300">{error}</p>
          <p className="text-xs text-slate-500">Socket target: {SOCKET_URL}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full bg-slate-950">
      <div className="relative flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
          onInit={(instance) => {
            flowRef.current = instance;
          }}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          panOnDrag
          zoomOnScroll
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1e293b" gap={20} />
          <MiniMap
            pannable
            zoomable
            nodeColor={(node) => {
              if (node.data?.kind === 'device') {
                return '#64748b';
              }
              return getEdgeStyle((node.data?.classification || 'legit') as Classification);
            }}
            maskColor="rgba(2, 6, 23, 0.55)"
            style={{ backgroundColor: '#020617', border: '1px solid #1e293b' }}
          />
          <Controls />
        </ReactFlow>

        <div className="absolute left-4 top-4 flex items-center gap-3 rounded-full border border-slate-700 bg-slate-950/90 px-4 py-2 text-sm text-slate-200 shadow-lg backdrop-blur">
          {connected ? <Wifi className="h-4 w-4 text-emerald-400" /> : <WifiOff className="h-4 w-4 text-red-400" />}
          <span>{connected ? 'Live Socket Connected' : 'Socket Reconnecting'}</span>
          <span className="text-slate-500">|</span>
          <span>{nodes.filter((node) => node.data.kind === 'network').length} networks</span>
          <span>{nodes.filter((node) => node.data.kind === 'device').length} devices</span>
        </div>

        <div className="absolute bottom-4 left-4 rounded-2xl border border-slate-800 bg-slate-950/90 px-4 py-3 text-xs text-slate-300 shadow-lg backdrop-blur">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-400" />
            <span>Click any network node to launch attack</span>
          </div>
        </div>
      </div>

      <aside className="h-full w-[340px] border-l border-slate-800 bg-slate-900/90 p-6">
        {selectedNode ? (
          <div className="space-y-5">
            <div>
              <div className="mb-2 flex items-center gap-2">
                {selectedNode.kind === 'network' ? (
                  <Zap className="h-5 w-5 text-cyan-400" />
                ) : (
                  <Shield className="h-5 w-5 text-slate-400" />
                )}
                <h3 className="text-lg font-semibold text-white">
                  {selectedNode.kind === 'network' ? 'Network Details' : 'Device Details'}
                </h3>
              </div>
              <p className="text-sm text-slate-400">
                {selectedNode.kind === 'network'
                  ? 'Live backend snapshot data'
                  : 'Client observed in the current snapshot'}
              </p>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Label</div>
              <div className="mt-2 text-base font-semibold text-white">{selectedNode.displayLabel}</div>
            </div>

            {selectedNode.kind === 'network' ? (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">BSSID</div>
                    <div className="mt-2 break-all font-mono text-sm text-slate-200">{selectedNode.bssid}</div>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Signal</div>
                    <div className="mt-2 text-sm text-slate-200">{selectedNode.signal ?? 'N/A'} dBm</div>
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Classification</div>
                    <div className="mt-2 text-sm text-slate-200">{selectedNode.classification}</div>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Last Seen</div>
                    <div className="mt-2 text-sm text-slate-200">{relativeLastSeen(selectedNode.last_seen)}</div>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Connected Clients</div>
                    <div className="text-xs text-slate-400">{selectedNode.clients?.length || 0}</div>
                  </div>
                  <div className="space-y-2">
                    {(selectedNode.clients || []).length > 0 ? (
                      (selectedNode.clients || []).map((client) => (
                        <div key={client.mac} className="rounded-xl border border-slate-800 bg-slate-900 px-3 py-2">
                          <div className="font-mono text-xs text-slate-200">{client.mac}</div>
                          <div className="mt-1 text-xs text-slate-500">{client.type || 'device'}</div>
                        </div>
                      ))
                    ) : (
                      <div className="text-sm text-slate-500">No client devices reported for this network.</div>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4">
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-500">MAC Address</div>
                  <div className="mt-2 break-all font-mono text-sm text-slate-200">{selectedNode.mac}</div>
                </div>
                <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4">
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Device Type</div>
                  <div className="mt-2 text-sm text-slate-200">{selectedNode.deviceType || 'device'}</div>
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center rounded-3xl border border-dashed border-slate-800 bg-slate-950 p-6 text-center text-sm text-slate-500">
            Select a node to inspect its live details.
          </div>
        )}
      </aside>
    </div>
  );
}
