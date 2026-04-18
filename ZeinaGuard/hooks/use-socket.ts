'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { io, Socket } from 'socket.io-client';


export interface LiveNetworkEvent {
  sensor_id: number;
  ssid: string;
  bssid: string;
  signal: number | null;
  channel: number | null;
  classification: 'ROGUE' | 'SUSPICIOUS' | 'LEGIT';
  timestamp: string;
  manufacturer: string | null;
  threat_id?: number;
  severity?: string;
  status?: string;
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
  status: 'online' | 'offline' | 'degraded' | 'starting' | 'monitoring' | 'capturing' | 'analyzing' | string;
  signal_strength: number;
  cpu?: number;
  cpu_usage: number;
  memory?: number;
  memory_usage: number;
  uptime: number;
  last_heartbeat: string;
  message?: string | null;
  interface?: string | null;
}

export interface AttackCommandEvent {
  sensor_id: number;
  action: string;
  target_bssid: string;
  channel: number | null;
  timestamp?: string;
  status?: string;
}

export interface AttackAckEvent {
  event: 'attack_ack';
  status: 'success' | 'failed';
  target_bssid: string;
  sensor_id: number;
  message?: string | null;
  timestamp: string;
}

interface UseSocketOptions {
  onNetworkScan?: (event: LiveNetworkEvent) => void;
  onNetworkUpdate?: (event: LiveNetworkEvent) => void;
  onThreatDetected?: (event: LiveNetworkEvent) => void;
  onAttackCommand?: (event: AttackCommandEvent) => void;
  onAttackAck?: (event: AttackAckEvent) => void;
  onSensorStatus?: (event: SensorStatusEvent) => void;
  onThreatEvent?: (event: ThreatEvent) => void;
  autoConnect?: boolean;
}


const SOCKET_EVENTS = [
  'network_scan',
  'network_update',
  'threat_detected',
  'attack_command',
  'attack_ack',
  'sensor_status',
] as const;


function resolveSocketUrl(): string {
  return process.env.NEXT_PUBLIC_SOCKET_URL || 'http://localhost:5000';
}


export function useSocket(options: UseSocketOptions = {}) {
  const {
    onNetworkScan,
    onNetworkUpdate,
    onThreatDetected,
    onAttackCommand,
    onAttackAck,
    onSensorStatus,
    onThreatEvent,
    autoConnect = true,
  } = options;

  const socketRef = useRef<Socket | null>(null);
  const [connected, setConnected] = useState(false);
  const handlersRef = useRef({
    onNetworkScan,
    onNetworkUpdate,
    onThreatDetected,
    onAttackCommand,
    onAttackAck,
    onSensorStatus,
    onThreatEvent,
  });

  useEffect(() => {
    handlersRef.current = {
      onNetworkScan,
      onNetworkUpdate,
      onThreatDetected,
      onAttackCommand,
      onAttackAck,
      onSensorStatus,
      onThreatEvent,
    };
  }, [onAttackAck, onAttackCommand, onNetworkScan, onNetworkUpdate, onSensorStatus, onThreatDetected, onThreatEvent]);

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

    socket.on('registration_success', (data) => {
      console.log('[EVENT RECEIVED] registration_success', data);
    });

    socket.on('registration_error', (data) => {
      console.log('[EVENT RECEIVED] registration_error', data);
    });

    socket.on('network_scan', (event: LiveNetworkEvent) => {
      console.log('[EVENT RECEIVED] network_scan', event);
      handlersRef.current.onNetworkScan?.(event);
    });

    socket.on('network_update', (event: LiveNetworkEvent) => {
      console.log('[EVENT RECEIVED] network_update', event);
      handlersRef.current.onNetworkUpdate?.(event);
    });

    socket.on('threat_detected', (event: LiveNetworkEvent) => {
      console.log('[EVENT RECEIVED] threat_detected', event);
      handlersRef.current.onThreatDetected?.(event);
    });

    socket.on('attack_command', (event: AttackCommandEvent) => {
      console.log('[EVENT RECEIVED] attack_command', event);
      handlersRef.current.onAttackCommand?.(event);
    });

    socket.on('attack_ack', (event: AttackAckEvent) => {
      console.log('[EVENT RECEIVED] attack_ack', event);
      handlersRef.current.onAttackAck?.(event);
    });

    socket.on('sensor_status', (event: SensorStatusEvent) => {
      console.log('[EVENT RECEIVED] sensor_status', event);
      handlersRef.current.onSensorStatus?.(event);
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

  const isConnected = useCallback(() => {
    return connected;
  }, [connected]);

  const getSocket = useCallback(() => {
    return socketRef.current;
  }, []);

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


export function useSensorStatus(onEvent?: (event: SensorStatusEvent) => void) {
  useSocket({
    onSensorStatus: onEvent,
  });
}
