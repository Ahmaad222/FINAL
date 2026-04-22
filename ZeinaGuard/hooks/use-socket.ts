'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { io, Socket } from 'socket.io-client';


export interface LiveNetworkEvent {
  sensor_id: number;
  ssid: string;
  bssid: string;
  signal: number | null;
  channel: number | null;
  classification: 'ROGUE' | 'SUSPICIOUS' | 'LEGIT';
  last_seen: string;
  timestamp?: string;
  manufacturer: string | null;
}

export interface NetworkSnapshotEvent {
  event: 'network_snapshot' | 'networks_snapshot';
  data: LiveNetworkEvent[];
}

type NetworkSnapshotPayload =
  | NetworkSnapshotEvent
  | LiveNetworkEvent[];

export interface NetworkRemovedEvent {
  bssid: string;
}

export interface ThreatEvent {
  type: 'threat_detected';
  timestamp: string;
  severity?: string;
  data: {
    id: number;
    threat_type: string;
    severity: string;
    source_mac: string;
    ssid: string;
    detected_by: number;
    description: string;
    signal_strength: number;
    packet_count: number;
    is_resolved: boolean;
    created_at: string;
  };
}

export interface SensorStatusEvent {
  sensor_id: number;
  status: string;
  cpu: number;
  memory: number;
  uptime: number;
  last_seen: string;
  last_heartbeat: string;
  message?: string | null;
  interface?: string | null;
  hostname?: string | null;
  connected?: boolean;
}

export interface SensorSnapshotEvent {
  event: 'sensor_snapshot';
  data: SensorStatusEvent[];
}

export interface SensorStatusUpdateEvent {
  event: 'sensor_status_update';
  data: SensorStatusEvent;
}

export interface AttackCommandEvent {
  sensor_id: number;
  bssid: string;
  action?: string;
  channel?: number | null;
  timestamp?: string;
  status?: string;
}

export interface AttackAckEvent {
  event: 'attack_ack';
  status: 'executed' | 'failed' | string;
  bssid: string;
  sensor_id: number;
  message?: string | null;
  timestamp: string;
}

export interface AttackCommandAckEvent {
  status: 'ok' | 'error';
  sensor_id?: number;
  bssid?: string;
  channel?: number | null;
  message?: string | null;
  timestamp: string;
}

interface UseSocketOptions {
  onNetworkSnapshot?: (event: NetworkSnapshotEvent) => void;
  onSensorSnapshot?: (event: SensorSnapshotEvent) => void;
  onSensorStatusUpdate?: (event: SensorStatusUpdateEvent) => void;
  onNetworkRemoved?: (event: NetworkRemovedEvent) => void;
  onThreatDetected?: (event: LiveNetworkEvent) => void;
  onAttackCommand?: (event: AttackCommandEvent) => void;
  onAttackCommandAck?: (event: AttackCommandAckEvent) => void;
  onAttackAck?: (event: AttackAckEvent) => void;
  onThreatEvent?: (event: ThreatEvent) => void;
  autoConnect?: boolean;
}


const SOCKET_EVENTS = [
  'network_snapshot',
  'networks_snapshot',
  'sensor_snapshot',
  'sensor_status_update',
  'network_removed',
  'threat_detected',
  'attack_command',
  'attack_command_ack',
  'attack_ack',
  'threat_event',
] as const;


function resolveSocketUrl(): string {
  return (
    process.env.NEXT_PUBLIC_SOCKET_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    'http://localhost:5000'
  );
}

function normalizeNetworkSnapshot(
  eventName: NetworkSnapshotEvent['event'],
  payload: NetworkSnapshotPayload,
): NetworkSnapshotEvent {
  if (Array.isArray(payload)) {
    return {
      event: eventName,
      data: payload,
    };
  }

  return {
    event: payload.event ?? eventName,
    data: Array.isArray(payload.data) ? payload.data : [],
  };
}


export function useSocket(options: UseSocketOptions = {}) {
  const {
    onNetworkSnapshot,
    onSensorSnapshot,
    onSensorStatusUpdate,
    onNetworkRemoved,
    onThreatDetected,
    onAttackCommand,
    onAttackCommandAck,
    onAttackAck,
    onThreatEvent,
    autoConnect = true,
  } = options;

  const socketRef = useRef<Socket | null>(null);
  const [connected, setConnected] = useState(false);
  const handlersRef = useRef({
    onNetworkSnapshot,
    onSensorSnapshot,
    onSensorStatusUpdate,
    onNetworkRemoved,
    onThreatDetected,
    onAttackCommand,
    onAttackCommandAck,
    onAttackAck,
    onThreatEvent,
  });

  useEffect(() => {
    handlersRef.current = {
      onNetworkSnapshot,
      onSensorSnapshot,
      onSensorStatusUpdate,
      onNetworkRemoved,
      onThreatDetected,
      onAttackCommand,
      onAttackCommandAck,
      onAttackAck,
      onThreatEvent,
    };
  }, [
    onAttackAck,
    onAttackCommand,
    onAttackCommandAck,
    onNetworkRemoved,
    onNetworkSnapshot,
    onSensorSnapshot,
    onSensorStatusUpdate,
    onThreatDetected,
    onThreatEvent,
  ]);

  const connect = useCallback(() => {
    if (socketRef.current) {
      return;
    }

    const socketUrl = resolveSocketUrl();
    const socket = io(socketUrl, {
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: Infinity,
      timeout: 10000,
      transports: ['websocket', 'polling'],
    });

    socket.on('connect', () => {
      setConnected(true);
      console.log('[SOCKET CONNECTED]', { socketUrl, id: socket.id });
    });

    socket.on('disconnect', (reason) => {
      setConnected(false);
      console.log('[SOCKET CONNECTED] disconnected', { reason });
    });

    socket.on('connect_error', (error) => {
      setConnected(false);
      console.error('[SOCKET CONNECTED] connect_error', error);
    });

    socket.on('connection_response', (data) => {
      console.log('[EVENT RECEIVED] connection_response', data);
    });

    socket.on('network_snapshot', (payload: NetworkSnapshotPayload) => {
      const event = normalizeNetworkSnapshot('network_snapshot', payload);
      handlersRef.current.onNetworkSnapshot?.(event);
    });

    socket.on('networks_snapshot', (payload: NetworkSnapshotPayload) => {
      const event = normalizeNetworkSnapshot('networks_snapshot', payload);
      handlersRef.current.onNetworkSnapshot?.(event);
    });

    socket.on('sensor_snapshot', (event: SensorSnapshotEvent) => {
      console.log('SNAPSHOT', event.data);
      handlersRef.current.onSensorSnapshot?.(event);
    });

    socket.on('sensor_status_update', (event: SensorStatusUpdateEvent) => {
      console.log('[EVENT RECEIVED] sensor_status_update', event);
      handlersRef.current.onSensorStatusUpdate?.(event);
    });

    socket.on('network_removed', (event: NetworkRemovedEvent) => {
      console.log('[EVENT RECEIVED] network_removed', event);
      handlersRef.current.onNetworkRemoved?.(event);
    });

    socket.on('threat_detected', (event: LiveNetworkEvent) => {
      console.log('[EVENT RECEIVED] threat_detected', event);
      handlersRef.current.onThreatDetected?.(event);
    });

    socket.on('attack_command', (event: AttackCommandEvent) => {
      console.log('[EVENT RECEIVED] attack_command', event);
      handlersRef.current.onAttackCommand?.(event);
    });

    socket.on('attack_command_ack', (event: AttackCommandAckEvent) => {
      console.log('[EVENT RECEIVED] attack_command_ack', event);
      handlersRef.current.onAttackCommandAck?.(event);
    });

    socket.on('attack_ack', (event: AttackAckEvent) => {
      console.log('[EVENT RECEIVED] attack_ack', event);
      handlersRef.current.onAttackAck?.(event);
    });

    socket.on('threat_event', (event: ThreatEvent) => {
      console.log('[EVENT RECEIVED] threat_event', event);
      handlersRef.current.onThreatEvent?.(event);
    });

    socketRef.current = socket;
  }, []);

  const disconnect = useCallback(() => {
    if (!socketRef.current) {
      return;
    }

    for (const eventName of SOCKET_EVENTS) {
      socketRef.current.off(eventName);
    }
    socketRef.current.disconnect();
    socketRef.current = null;
    setConnected(false);
  }, []);

  const isConnected = useCallback(() => connected, [connected]);

  const getSocket = useCallback(() => socketRef.current, []);

  const sendAttackCommand = useCallback((payload: AttackCommandEvent) => {
    if (!socketRef.current?.connected) {
      throw new Error('Socket is not connected');
    }

    console.log('[SOCKET EMIT] attack_command', payload);
    socketRef.current.emit('attack_command', payload);
  }, []);

  useEffect(() => {
    if (!autoConnect) {
      return;
    }

    connect();
    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return {
    connect,
    disconnect,
    isConnected,
    getSocket,
    sendAttackCommand,
  };
}


export function useThreatEvents(onEvent?: (event: ThreatEvent) => void) {
  useSocket({
    onThreatEvent: onEvent,
  });
}


export function useSensorStatus(onEvent?: (event: SensorStatusUpdateEvent) => void) {
  useSocket({
    onSensorStatusUpdate: onEvent,
  });
}
