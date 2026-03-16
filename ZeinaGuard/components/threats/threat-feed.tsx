'use client';

import { useState, useEffect } from 'react';
import { useSocket, ThreatEvent } from '@/hooks/use-socket';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertTriangle, AlertCircle, WifiOff } from 'lucide-react';

interface ThreatItem extends ThreatEvent {
  id?: string;
}

export function ThreatFeed() {
  const [threats, setThreats] = useState<ThreatItem[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [latestThreatTime, setLatestThreatTime] = useState<string | null>(null);

  const handleThreatEvent = (event: ThreatEvent) => {
    if (!event || !event.data) return;

    const threatItem: ThreatItem = {
      ...event,
      id: `${event.timestamp}-${Math.random()}`
    };

    setThreats(prev => [threatItem, ...prev].slice(0, 50));

    if (event.timestamp) {
      setLatestThreatTime(event.timestamp);
    }

    if (event.severity === 'critical') {
      flashCriticalAlert();
    }
  };

  const { isConnected: isSocketConnected } = useSocket({
    onThreatEvent: handleThreatEvent
  });

  useEffect(() => {
    const interval = setInterval(() => {
      setIsConnected(isSocketConnected());
    }, 1000);

    return () => clearInterval(interval);
  }, [isSocketConnected]);

  const flashCriticalAlert = () => {
    const body = document.body;
    const originalBg = body.style.backgroundColor;

    body.style.backgroundColor = '#7f1d1d';

    setTimeout(() => {
      body.style.backgroundColor = originalBg;
    }, 200);

    setTimeout(() => {
      body.style.backgroundColor = '#7f1d1d';
    }, 400);

    setTimeout(() => {
      body.style.backgroundColor = originalBg;
    }, 600);
  };

  const getSeverityColor = (severity?: string) => {
    switch (severity) {
      case 'critical':
        return 'bg-red-900 text-red-100 border-red-700';
      case 'high':
        return 'bg-orange-900 text-orange-100 border-orange-700';
      case 'medium':
        return 'bg-yellow-900 text-yellow-100 border-yellow-700';
      case 'low':
        return 'bg-blue-900 text-blue-100 border-blue-700';
      default:
        return 'bg-slate-700 text-slate-100 border-slate-600';
    }
  };

  const getSeverityIcon = (severity?: string) => {
    if (severity === 'critical' || severity === 'high') {
      return <AlertTriangle className="w-4 h-4" />;
    }
    return <AlertCircle className="w-4 h-4" />;
  };

  const getThreatTypeLabel = (threatType?: string) => {
    if (!threatType) return "Unknown Threat";

    return threatType
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  return (
    <div className="space-y-4">
      {/* Connection Status */}
      <Card className={`bg-${isConnected ? 'green' : 'red'}-900 border-${isConnected ? 'green' : 'red'}-700`}>
        <CardContent className="pt-6 flex items-center gap-3">
          {isConnected ? (
            <>
              <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
              <p className="text-green-100">WebSocket Connected - Ready for real-time threat events</p>
            </>
          ) : (
            <>
              <WifiOff className="w-4 h-4 text-red-400" />
              <p className="text-red-100">WebSocket Disconnected - Reconnecting...</p>
            </>
          )}
        </CardContent>
      </Card>

      {/* Latest Threat */}
      {latestThreatTime && (
        <Alert className="bg-red-900 border-red-700">
          <AlertDescription className="text-red-100">
            Latest threat detected at {new Date(latestThreatTime).toLocaleTimeString()}
          </AlertDescription>
        </Alert>
      )}

      {/* Header */}
      <Card className="bg-slate-800 border-slate-700">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2">
            <span>Real-Time Threat Feed</span>
            <Badge variant="outline" className="ml-auto bg-slate-700 text-slate-100">
              {threats.length} threats
            </Badge>
          </CardTitle>
          <CardDescription className="text-slate-400">
            Live threat events streaming via WebSocket
          </CardDescription>
        </CardHeader>
      </Card>

      {/* Threats List */}
      <div className="space-y-3">
        {threats.length === 0 ? (
          <Card className="bg-slate-800 border-slate-700">
            <CardContent className="pt-6 text-center text-slate-400">
              <p>No threats detected yet</p>
              <p className="text-sm mt-2">
                When threats are detected, they will appear here in real-time
              </p>
            </CardContent>
          </Card>
        ) : (
          threats.map(threat => {
            const data = threat.data || {};
            return (
              <Card
                key={threat.id}
                className={`${getSeverityColor(threat.severity)} border-2`}
              >
                <CardContent className="pt-6">
                  <div className="flex items-start gap-3">
                    {getSeverityIcon(threat.severity)}
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-semibold">
                          {getThreatTypeLabel(data.threat_type)}
                        </h3>
                        <Badge variant="outline" className="text-xs">
                          {(threat.severity || "info").toUpperCase()}
                        </Badge>
                      </div>
                      <p className="text-sm mb-2">
                        {data.description || "No description available"}
                      </p>
                      <div className="text-xs space-y-1">
                        <p>Source MAC: {data.source_mac || "-"}</p>
                        <p>SSID: {data.ssid || "-"}</p>
                        <p>Signal Strength: {data.signal_strength ?? "-"} dBm</p>
                        <p>Packets: {data.packet_count ?? "-"}</p>
                        <p>
                          Detected: {data.created_at
                            ? new Date(data.created_at).toLocaleString()
                            : "-"
                          }
                        </p>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })
        )}
      </div>

      {/* Status Footer */}
      <Card className="bg-slate-800 border-slate-700">
        <CardHeader>
          <CardTitle className="text-white text-sm">Phase 2 Status</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-slate-300 space-y-1">
          <p>✓ Socket.io WebSocket connection established</p>
          <p>✓ Real-time threat event broadcasting</p>
          <p>✓ Threat feed UI with live updates</p>
          <p>✓ Severity-based color coding and alerts</p>
        </CardContent>
      </Card>
    </div>
  );
}
