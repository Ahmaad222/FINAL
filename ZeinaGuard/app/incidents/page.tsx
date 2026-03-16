'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@/hooks/use-auth';
import { apiClient } from '@/lib/api';
import { AlertTriangle, Clock, CheckCircle, Activity } from 'lucide-react';

interface Incident {
  id: number;
  title: string;
  description: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  status: 'open' | 'in_progress' | 'resolved';
  created_at: string;
  updated_at: string;
  assigned_to: string;
}

export default function IncidentsPage() {
  const { user, token } = useAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'open' | 'in_progress' | 'resolved'>('all');

  useEffect(() => {
    if (!token) return;

    const fetchIncidents = async () => {
      try {
        setLoading(true);
        const response = await apiClient.get('/api/incidents', token);
        setIncidents(response.data);
      } catch (error) {
        console.error('Failed to fetch incidents:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchIncidents();
  }, [token]);

  const filteredIncidents = incidents.filter((incident) => {
    if (filter === 'all') return true;
    return incident.status === filter;
  });

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'open':
        return 'bg-red-900 text-red-100';
      case 'in_progress':
        return 'bg-yellow-900 text-yellow-100';
      case 'resolved':
        return 'bg-green-900 text-green-100';
      default:
        return 'bg-slate-700 text-slate-100';
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'text-red-400';
      case 'high':
        return 'text-orange-400';
      case 'medium':
        return 'text-yellow-400';
      case 'low':
        return 'text-blue-400';
      default:
        return 'text-slate-400';
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 p-8 flex items-center justify-center">
        <div className="text-slate-300">Loading incidents...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-white flex items-center gap-3">
            <AlertTriangle className="w-10 h-10 text-orange-500" />
            Incident Response
          </h1>
          <p className="text-slate-400 mt-2">
            Track and manage security incidents
          </p>
        </div>

        {/* Filter Tabs */}
        <div className="flex gap-4 mb-8 border-b border-slate-700 pb-4">
          {['all', 'open', 'in_progress', 'resolved'].map((status) => (
            <button
              key={status}
              onClick={() => setFilter(status as any)}
              className={`px-4 py-2 font-medium transition-colors ${
                filter === status
                  ? 'text-blue-400 border-b-2 border-blue-500 -mb-4 pb-2'
                  : 'text-slate-400 hover:text-slate-300'
              }`}
            >
              {status.charAt(0).toUpperCase() + status.slice(1).replace('_', ' ')}
            </button>
          ))}
        </div>

        {/* Incidents List */}
        <div className="space-y-4">
          {filteredIncidents.map((incident) => (
            <div
              key={incident.id}
              className="bg-slate-800 border border-slate-700 rounded-lg p-6 hover:border-slate-600 transition-colors"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="text-lg font-semibold text-white">
                      Incident #{incident.id}: {incident.title}
                    </h3>
                    <span
                      className={`text-xs font-medium px-3 py-1 rounded-full ${getStatusColor(
                        incident.status
                      )}`}
                    >
                      {incident.status.toUpperCase().replace('_', ' ')}
                    </span>
                  </div>
                  <p className="text-slate-400 text-sm">{incident.description}</p>
                </div>
                <AlertTriangle className={`w-6 h-6 ${getSeverityColor(incident.severity)}`} />
              </div>

              {/* Details */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-slate-700">
                <div>
                  <p className="text-xs text-slate-500">Severity</p>
                  <p className={`font-semibold ${getSeverityColor(incident.severity)}`}>
                    {incident.severity.toUpperCase()}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Assigned To</p>
                  <p className="font-semibold text-white">{incident.assigned_to}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500 flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    Created
                  </p>
                  <p className="font-semibold text-white text-sm">
                    {new Date(incident.created_at).toLocaleDateString()}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500 flex items-center gap-1">
                    <Activity className="w-3 h-3" />
                    Last Updated
                  </p>
                  <p className="font-semibold text-white text-sm">
                    {new Date(incident.updated_at).toLocaleDateString()}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>

        {filteredIncidents.length === 0 && (
          <div className="text-center py-12">
            <CheckCircle className="w-16 h-16 text-slate-600 mx-auto mb-4" />
            <p className="text-slate-400 text-lg">
              No {filter !== 'all' ? filter.replace('_', ' ') : ''} incidents found
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
