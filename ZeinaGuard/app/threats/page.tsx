'use client';

import { useAuth } from '@/hooks/use-auth';
import { ProtectedRoute } from '@/components/auth/protected-route';
import { Button } from '@/components/ui/button';
import { useRouter } from 'next/navigation';
import { ThreatFeed } from '@/components/threats/threat-feed';
import { ThreatSimulator } from '@/components/threats/threat-simulator';

function ThreatsContent() {
  const router = useRouter();
  const { user, logout } = useAuth();

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
      <div className="bg-slate-800 border-b border-slate-700">
        <div className="max-w-6xl mx-auto px-4 py-4 flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-white">ZeinaGuard Pro</h1>
            <p className="text-sm text-slate-400">Real-Time Threat Feed</p>
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

      {/* Main Content */}
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Navigation */}
        <div className="mb-8 flex gap-2">
          <Button 
            variant="outline" 
            onClick={() => router.push('/dashboard')}
            className="text-slate-300"
          >
            Dashboard
          </Button>
          <Button 
            variant="default"
            onClick={() => router.push('/threats')}
            className="bg-blue-600"
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
        </div>

        {/* Two Column Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Threat Feed - Main Column */}
          <div className="lg:col-span-2">
            <ThreatFeed />
          </div>

          {/* Sidebar */}
          <div className="space-y-4">
            {/* Threat Simulator */}
            <ThreatSimulator />

            {/* Info Card */}
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
              <h3 className="font-semibold text-white mb-3">Phase 2 Features</h3>
              <ul className="text-sm text-slate-300 space-y-2">
                <li className="flex gap-2">
                  <span className="text-green-400">✓</span>
                  <span>WebSocket Real-Time Connection</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-green-400">✓</span>
                  <span>Threat Event Broadcasting</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-green-400">✓</span>
                  <span>Live Threat Feed UI</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-green-400">✓</span>
                  <span>Severity Color Coding</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-green-400">✓</span>
                  <span>Critical Alert Feedback</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-yellow-500">~</span>
                  <span>Sensor Heartbeat Monitoring</span>
                </li>
              </ul>
            </div>

            {/* Instructions */}
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
              <h3 className="font-semibold text-white mb-3 text-sm">How to Test</h3>
              <ol className="text-xs text-slate-300 space-y-2 list-decimal list-inside">
                <li>Open this page in 2 browser windows</li>
                <li>Click "Simulate Critical Threat" in one window</li>
                <li>See the threat appear instantly in both windows</li>
                <li>Watch as both screens flash red for critical threats</li>
                <li>Observe real-time updates via WebSocket ({"<"} 500ms latency)</li>
              </ol>
            </div>

            {/* Architecture Info */}
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
              <h3 className="font-semibold text-white mb-3 text-sm">Architecture</h3>
              <pre className="text-xs bg-slate-900 p-2 rounded overflow-auto text-slate-300">
{`Flask Backend
    ↓
Socket.io Server
    ↓
Redis Event Bus
    ↓
Next.js WebSocket
    ↓
Live UI Update`}
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ThreatsPage() {
  return (
    <ProtectedRoute>
      <ThreatsContent />
    </ProtectedRoute>
  );
}
