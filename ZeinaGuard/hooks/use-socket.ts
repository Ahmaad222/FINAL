/**
 * useSocket Hook - Real-time WebSocket connection
 */

import { useEffect, useRef, useCallback } from 'react';
import { io, Socket } from 'socket.io-client';

export interface ThreatEvent {
  type: 'threat_detected';
  timestamp: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  threat_type: string;
  data: any;
}

export interface SensorStatusEvent {
  type: 'sensor_status';
  timestamp: string;
  data: any;
}

interface UseSocketOptions {
  onThreatEvent?: (event: ThreatEvent) => void;
  onSensorStatus?: (event: SensorStatusEvent) => void;
  autoConnect?: boolean;
}

export function useSocket(options: UseSocketOptions = {}) {

  const {
    onThreatEvent,
    onSensorStatus,
    autoConnect = true
  } = options;

  const socketRef = useRef<Socket | null>(null);

  const connect = useCallback(() => {

    if (socketRef.current?.connected) return;

    try {

      const socketUrl =
        process.env.NEXT_PUBLIC_SOCKET_URL ||
        'http://192.168.201.130:5001';

      console.log('[Socket] Connecting to:', socketUrl);

      socketRef.current = io(socketUrl, {
        transports: ['websocket'],
        reconnection: true,
        reconnectionAttempts: 10,
        reconnectionDelay: 1000
      });

      socketRef.current.on('connect', () => {

        console.log('[Socket] ✅ Connected');

        subscribeToThreats();
        subscribeToSensors();

      });

      socketRef.current.on('disconnect', (reason) => {
        console.log('[Socket] Disconnected:', reason);
      });

      socketRef.current.on('connect_error', (error) => {
        console.error('[Socket] Connection error:', error);
      });

      socketRef.current.on('threat_event', (event: ThreatEvent) => {

        console.log('[Socket] Threat event:', event);

        if (onThreatEvent) onThreatEvent(event);

      });

      socketRef.current.on('sensor_status', (event: SensorStatusEvent) => {

        console.log('[Socket] Sensor status:', event);

        if (onSensorStatus) onSensorStatus(event);

      });

      socketRef.current.on('connection_response', (data) => {
        console.log('[Socket] Server response:', data);
      });

      socketRef.current.on('subscription_response', (data) => {
        console.log('[Socket] Subscription:', data);
      });

    } catch (error) {

      console.error('[Socket] Failed to connect:', error);

    }

  }, [onThreatEvent, onSensorStatus]);

  const disconnect = useCallback(() => {

    if (socketRef.current) {

      socketRef.current.disconnect();
      socketRef.current = null;

    }

  }, []);

  const subscribeToThreats = () => {

    socketRef.current?.emit('subscribe_threats');

  };

  const subscribeToSensors = () => {

    socketRef.current?.emit('subscribe_sensors');

  };

  const isConnected = () => socketRef.current?.connected ?? false;

  useEffect(() => {

    if (autoConnect) connect();

    return () => disconnect();

  }, [connect, disconnect, autoConnect]);

  return {
    connect,
    disconnect,
    isConnected
  };

}
