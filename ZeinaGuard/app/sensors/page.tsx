'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@/hooks/use-auth';
import { apiClient } from '@/lib/api';
import { Activity, Wifi, Signal, Clock } from 'lucide-react';

interface Sensor {
  id: number;
  hostname: string;
  location: string;
  status: 'online' | 'offline' | 'degraded';
  signal_strength: number;
  uptime_percent: number;
  last_seen: string;
  packet_count: number;
  coverage_area: string;
}

export default function SensorsPage() {
  const { user, token } = useAuth();
  const [sensors, setSensors] = useState<Sensor[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;

    const fetchSensors = async () => {
      try {
        setLoading(true);
        const response = await apiClient.get('/api/sensors', token);
        setSensors(response.data);
      } catch (error) {
        console.error('Failed to fetch sensors:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchSensors();
    const interval = setInterval(fetchSensors, 5000); // Refresh every 5 seconds
    return () => clearInterval(interval);
  }, [token]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'online':
        return 'bg-green-900 text-green-100';
      case 'offline':
        return 'bg-red-900 text-red-100';
      case 'degraded':
        return 'bg-yellow-900 text-yellow-100';
      default:
        return 'bg-slate-700 text-slate-100';
    }
  };

  const getSignalIndicator = (strength: number) => {
    if (strength >= -40) return 'Excellent';
    if (strength >= -55) return 'Good';
    if (strength >= -70) return 'Fair';
    return 'Poor';
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 p-8 flex items-center justify-center">
        <div className="text-slate-300">Loading sensors...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-white flex items-center gap-3">
            <Wifi className="w-10 h-10 text-blue-500" />
            Sensor Management
          </h1>
          <p className="text-slate-400 mt-2">
            Manage and monitor all wireless sensors
          </p>
        </div>

        {/* Sensor Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {sensors.map((sensor) => (
            <div
              key={sensor.id}
              className="bg-slate-800 border border-slate-700 rounded-lg p-6 hover:border-slate-600 transition-colors"
            >
              {/* Header */}
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-xl font-semibold text-white">
                    {sensor.hostname}
                  </h3>
                  <p className="text-sm text-slate-400">{sensor.location}</p>
                </div>
                <span
                  className={`text-xs font-medium px-3 py-1 rounded-full flex items-center gap-1 ${getStatusColor(
                    sensor.status
                  )}`}
                >
                  <Activity className="w-3 h-3" />
                  {sensor.status.toUpperCase()}
                </span>
              </div>

              {/* Signal Strength Sparkline */}
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm text-slate-400">Signal Strength</label>
                  <span className="text-sm font-medium text-blue-400">
                    {getSignalIndicator(sensor.signal_strength)}
                  </span>
                </div>
                <div className="bg-slate-700 rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-gradient-to-r from-blue-500 to-blue-600 h-full transition-all"
                    style={{
                      width: `${Math.min(100, (sensor.signal_strength + 100) * 1.2)}%`,
                    }}
                  />
                </div>
                <p className="text-xs text-slate-500 mt-1">{sensor.signal_strength} dBm</p>
              </div>

              {/* Uptime Indicator */}
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm text-slate-400 flex items-center gap-2">
                    <Clock className="w-3 h-3" />
                    Uptime
                  </label>
                  <span className="text-sm font-medium text-green-400">
                    {sensor.uptime_percent}%
                  </span>
                </div>
                <div className="bg-slate-700 rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-gradient-to-r from-green-500 to-green-600 h-full transition-all"
                    style={{ width: `${sensor.uptime_percent}%` }}
                  />
                </div>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-4 pt-4 border-t border-slate-700">
                <div>
                  <p className="text-xs text-slate-400">Packets</p>
                  <p className="text-lg font-semibold text-white">
                    {sensor.packet_count.toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">Coverage</p>
                  <p className="text-lg font-semibold text-white">
                    {sensor.coverage_area}
                  </p>
                </div>
              </div>

              {/* Last Seen */}
              <div className="mt-4 pt-4 border-t border-slate-700">
                <p className="text-xs text-slate-500">
                  Last seen: {new Date(sensor.last_seen).toLocaleTimeString()}
                </p>
              </div>
            </div>
          ))}
        </div>

        {sensors.length === 0 && (
          <div className="text-center py-12">
            <Wifi className="w-16 h-16 text-slate-600 mx-auto mb-4" />
            <p className="text-slate-400 text-lg">No sensors found</p>
          </div>
        )}
      </div>
    </div>
  );
}
