'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/use-auth';
import { ProtectedRoute } from '@/components/auth/protected-route';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { MetricsCard } from '@/components/dashboard/metrics-card';
import { ThreatTimelineChart } from '@/components/dashboard/threat-timeline-chart';
import { AlertTriangle, Shield, Activity, AlertCircle, Cpu, Wifi } from 'lucide-react';

interface DashboardData {
  threats?: {
    total: number;
    critical: number;
    high: number;
    resolved: number;
    today: number;
  };
  sensors?: {
    total: number;
    online: number;
    offline: number;
    recent: Array<{
      sensor_id: number;
      name: string;
      status: string;
      signal_strength: number;
      cpu_usage: number;
      memory_usage: number;
    }>;
  };
  incidents?: {
    open: number;
    resolved: number;
  };
  alerts?: {
    unread: number;
    unacknowledged: number;
  };
}

function DashboardContent() {
  const router = useRouter();
  const { user, logout } = useAuth();
  const [dashboardData, setDashboardData] = useState<DashboardData>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchDashboardData = async () => {
    try {
      setRefreshing(true);
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000'}/api/dashboard/overview`,
        {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('zeinaguard_access_token')}`,
          },
        }
      );

      if (!response.ok) throw new Error('Failed to fetch dashboard data');

      const data = await response.json();
      setDashboardData(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 30000); // Refresh every 30 seconds
    return () => clearInterval(interval);
  }, []);

  const handleLogout = async () => {
    try {
      await logout();
      router.push('/login');
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 to-slate-950">
      {/* Header */}
      <div className="bg-slate-800 border-b border-slate-700 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-white">ZeinaGuard Pro</h1>
            <p className="text-sm text-slate-400">Security Dashboard</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="text-sm font-semibold text-white">{user?.username}</p>
              <p className="text-xs text-slate-400">{user?.email}</p>
            </div>
            <Button variant="outline" onClick={handleLogout}>
              Logout
            </Button>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <div className="bg-slate-800 border-b border-slate-700">
        <div className="max-w-7xl mx-auto px-4 py-3 flex gap-2">
          <Button
            variant="default"
            onClick={() => router.push('/dashboard')}
            className="bg-blue-600"
          >
            Dashboard
          </Button>
          <Button
            variant="outline"
            onClick={() => router.push('/threats')}
            className="text-slate-300"
          >
            Real-Time Threats
          </Button>
          <Button
            variant="outline"
            onClick={() => router.push('/sensors')}
            className="text-slate-300"
          >
            Sensors
          </Button>
          <Button
            variant="outline"
            onClick={fetchDashboardData}
            disabled={refreshing}
            className="ml-auto text-slate-300"
          >
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 py-8">
        {error && (
          <Alert variant="destructive" className="mb-6">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {loading ? (
          <div className="flex items-center justify-center min-h-96 text-slate-400">
            <div className="text-center">
              <Activity className="w-12 h-12 mx-auto mb-4 animate-spin opacity-50" />
              <p>Loading dashboard...</p>
            </div>
          </div>
        ) : (
          <div className="space-y-8">
            {/* Critical Alert Section */}
            {dashboardData.threats?.critical! > 0 && (
              <Alert className="bg-red-900 border-red-700">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription className="text-red-100">
                  <strong>{dashboardData.threats?.critical} critical threats</strong> detected and awaiting response
                </AlertDescription>
              </Alert>
            )}

            {/* Top Metrics */}
            <div>
              <h2 className="text-xl font-semibold text-white mb-4">Overview</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <MetricsCard
                  title="Critical Threats"
                  value={dashboardData.threats?.critical ?? 0}
                  description="Unresolved critical level"
                  icon={<AlertTriangle className="w-5 h-5 text-red-500" />}
                  bgColor="bg-red-950"
                  textColor="text-red-100"
                  borderColor="border-red-700"
                />

                <MetricsCard
                  title="High Severity"
                  value={dashboardData.threats?.high ?? 0}
                  description="Requires attention"
                  icon={<AlertCircle className="w-5 h-5 text-orange-500" />}
                  bgColor="bg-orange-950"
                  textColor="text-orange-100"
                  borderColor="border-orange-700"
                />

                <MetricsCard
                  title="Open Incidents"
                  value={dashboardData.incidents?.open ?? 0}
                  description="Active investigations"
                  icon={<Shield className="w-5 h-5 text-blue-500" />}
                  bgColor="bg-blue-950"
                  textColor="text-blue-100"
                  borderColor="border-blue-700"
                />

                <MetricsCard
                  title="Sensors Online"
                  value={`${dashboardData.sensors?.online ?? 0}/${dashboardData.sensors?.total ?? 0}`}
                  description="Monitoring network"
                  icon={<Wifi className="w-5 h-5 text-green-500" />}
                  bgColor="bg-green-950"
                  textColor="text-green-100"
                  borderColor="border-green-700"
                />
              </div>
            </div>

            {/* Threat Timeline */}
            <ThreatTimelineChart />

            {/* Sensor Health & Incidents */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Sensor Health */}
              <Card className="bg-slate-800 border-slate-700">
                <CardHeader>
                  <CardTitle className="text-white flex items-center gap-2">
                    <Cpu className="w-5 h-5 text-blue-400" />
                    Sensor Health
                  </CardTitle>
                  <CardDescription className="text-slate-400">
                    Current sensor metrics
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    {dashboardData.sensors?.recent?.slice(0, 3).map((sensor) => (
                      <div key={sensor.sensor_id} className="p-3 bg-slate-700 rounded">
                        <div className="flex justify-between items-start mb-2">
                          <h4 className="font-semibold text-white text-sm">{sensor.name}</h4>
                          <span
                            className={`text-xs px-2 py-1 rounded ${
                              sensor.status === 'online'
                                ? 'bg-green-900 text-green-100'
                                : 'bg-red-900 text-red-100'
                            }`}
                          >
                            {sensor.status}
                          </span>
                        </div>
                        <div className="text-xs text-slate-300 space-y-1">
                          <div className="flex justify-between">
                            <span>Signal: {sensor.signal_strength}%</span>
                            <span>CPU: {(sensor.cpu_usage || 0).toFixed(1)}%</span>
                          </div>
                          <div>Memory: {(sensor.memory_usage || 0).toFixed(1)}%</div>
                        </div>
                      </div>
                    ))}
                  </div>
                  <Button
                    variant="outline"
                    onClick={() => router.push('/sensors')}
                    className="w-full mt-4 text-slate-300"
                  >
                    View All Sensors
                  </Button>
                </CardContent>
              </Card>

              {/* Threats Summary */}
              <Card className="bg-slate-800 border-slate-700">
                <CardHeader>
                  <CardTitle className="text-white flex items-center gap-2">
                    <AlertTriangle className="w-5 h-5 text-red-400" />
                    Threat Summary
                  </CardTitle>
                  <CardDescription className="text-slate-400">
                    Current threat status
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    <div className="p-3 bg-red-900 rounded border border-red-700">
                      <div className="flex justify-between items-center">
                        <span className="text-red-100 text-sm">Critical</span>
                        <span className="text-2xl font-bold text-red-100">
                          {dashboardData.threats?.critical ?? 0}
                        </span>
                      </div>
                    </div>
                    <div className="p-3 bg-orange-900 rounded border border-orange-700">
                      <div className="flex justify-between items-center">
                        <span className="text-orange-100 text-sm">High</span>
                        <span className="text-2xl font-bold text-orange-100">
                          {dashboardData.threats?.high ?? 0}
                        </span>
                      </div>
                    </div>
                    <div className="p-3 bg-green-900 rounded border border-green-700">
                      <div className="flex justify-between items-center">
                        <span className="text-green-100 text-sm">Resolved Today</span>
                        <span className="text-2xl font-bold text-green-100">
                          {dashboardData.threats?.today ?? 0}
                        </span>
                      </div>
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    onClick={() => router.push('/threats')}
                    className="w-full mt-4 text-slate-300"
                  >
                    View All Threats
                  </Button>
                </CardContent>
              </Card>
            </div>

            {/* Stats Footer */}
            <Card className="bg-slate-800 border-slate-700">
              <CardHeader>
                <CardTitle className="text-white">Phase 4 Status</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-slate-300 space-y-1">
                <p>✓ Database-backed dashboard metrics</p>
                <p>✓ Real-time threat statistics</p>
                <p>✓ Sensor health monitoring</p>
                <p>✓ Incident tracking</p>
                <p>✓ 24-hour threat timeline chart</p>
                <p>✓ Auto-refreshing metrics (30s interval)</p>
                <p>Next: Command palette and advanced filtering</p>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <ProtectedRoute>
      <DashboardContent />
    </ProtectedRoute>
  );
}
