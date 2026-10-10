import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { 
  ShieldAlert, 
  Calendar, 
  Eye, 
  Users, 
  Swords, 
  Footprints, 
  Lock,
  AlertTriangle
} from 'lucide-react';
import { Link } from 'react-router-dom';

export const Events: React.FC = () => {
  const [selectedFilter, setSelectedFilter] = useState<string>('ALL');

  const { data: events, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['events-list'],
    queryFn: async () => {
      const response = await api.get('/events');
      return response.data || [];
    },
    staleTime: 30000,
  });

  
  // Filter events based on active category tab
  const filteredEvents = React.useMemo(() => {
    if (!events) return [];
    if (selectedFilter === 'ALL') return events;
    return events.filter((ev: any) => {
      const type = (ev.event_type || '').toUpperCase();
      if (selectedFilter === 'FIGHT') return type.includes('FIGHT') || type.includes('VIOLENCE');
      if (selectedFilter === 'BOUNDARY') return type.includes('FENCE') || type.includes('BOUNDARY') || type.includes('JUMP');
      if (selectedFilter === 'RESTRICTED') return type.includes('RESTRICTED') || type.includes('ENTRY');
      if (selectedFilter === 'SUSPICIOUS') return type.includes('SUSPICIOUS') || type.includes('ANOMALY');
      return true;
    });
  }, [events, selectedFilter]);

  const getEventBadgeClass = (typeStr: string) => {
    const type = (typeStr || '').toUpperCase();
    if (type.includes('VIOLENCE') || type.includes('FIGHT')) {
      return {
        badge: 'bg-red-50 text-red-700 border-red-200',
        icon: <Swords className="h-4 w-4 text-red-600" />,
        label: '⚠ Violence Detected'
      };
    } else if (type.includes('FENCE') || type.includes('BOUNDARY') || type.includes('JUMP')) {
      return {
        badge: 'bg-amber-50 text-amber-700 border-amber-200',
        icon: <Footprints className="h-4 w-4 text-amber-600" />,
        label: 'Boundary / Fence Jump'
      };
    } else if (type.includes('RESTRICTED') || type.includes('ENTRY')) {
      return {
        badge: 'bg-purple-50 text-purple-700 border-purple-200',
        icon: <Lock className="h-4 w-4 text-purple-600" />,
        label: 'Restricted Area Entry'
      };
    } else {
      return {
        badge: 'bg-yellow-50 text-yellow-700 border-yellow-200',
        icon: <AlertTriangle className="h-4 w-4 text-yellow-600" />,
        label: 'Suspicious Activity'
      };
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 h-96">
        <p className="animate-pulse font-semibold text-sm">Loading real-time surveillance alerts...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-slate-600 h-96 space-y-4">
        <p className="text-rose-600 font-medium">Failed to load surveillance alerts</p>
        <p className="text-xs text-slate-400 max-w-md text-center">
          {(error as any)?.response?.data?.detail || (error as any)?.message || 'An unexpected network error occurred.'}
        </p>
        <button
          onClick={() => refetch()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold transition shadow-sm"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-8 py-2">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Security Alerts Log</h2>
          <p className="text-slate-500 text-sm">Real-time surveillance triggers: Fights, fence jumps, boundary crossings, and unauthorized entries</p>
        </div>

        {/* Total count indicator */}
        <div className="flex items-center space-x-2 bg-white border border-slate-200 px-4 py-2 rounded-xl text-xs font-mono shadow-sm">
          <span className="text-slate-500">Total Recorded Alerts:</span>
          <span className="font-bold text-blue-600 text-sm">{events?.length || 0}</span>
        </div>
      </div>

      {/* Category Filter Tabs */}
      <div className="flex flex-wrap gap-2 bg-white p-2 rounded-2xl border border-slate-200 shadow-sm">
        {[
          { id: 'ALL', label: 'All Alerts', icon: <ShieldAlert className="h-3.5 w-3.5" /> },
          { id: 'FIGHT', label: 'Violence & Altercations', icon: <Swords className="h-3.5 w-3.5 text-red-600" /> },
          { id: 'BOUNDARY', label: 'Fence Jumps & Boundary', icon: <Footprints className="h-3.5 w-3.5 text-amber-600" /> },
          { id: 'RESTRICTED', label: 'Restricted Area Entries', icon: <Lock className="h-3.5 w-3.5 text-purple-600" /> },
          { id: 'SUSPICIOUS', label: 'Suspicious Activities', icon: <AlertTriangle className="h-3.5 w-3.5 text-yellow-600" /> },
        ].map((tab) => {
          const isActive = selectedFilter === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setSelectedFilter(tab.id)}
              className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
                isActive
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Alerts Table */}
      <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-200 text-xs font-semibold text-slate-500 bg-slate-50">
                <th className="px-6 py-4">Event Type / Camera</th>
                <th className="px-6 py-4">Date / Time</th>
                <th className="px-6 py-4">Confidence</th>
                <th className="px-6 py-4">Target Identity (Engaged Students)</th>
                <th className="px-6 py-4 text-right">Actions & Inspection</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm text-slate-700">
              {filteredEvents && filteredEvents.length > 0 ? (
                filteredEvents.map((ev: any) => {
                  const badgeInfo = getEventBadgeClass(ev.event_type);
                  return (
                    <tr key={ev.id} className="hover:bg-slate-50 transition">
                      {/* Event Type & Camera */}
                      <td className="px-6 py-4">
                        <div className="flex items-center space-x-3">
                          <div className={`p-2.5 rounded-xl border ${badgeInfo.badge}`}>
                            {badgeInfo.icon}
                          </div>
                          <div>
                            <span className={`text-xs font-bold px-2 py-0.5 rounded border uppercase inline-block mb-1 ${badgeInfo.badge}`}>
                              {badgeInfo.label}
                            </span>
                            <span className="font-semibold text-slate-900 block text-xs">
                              Camera: {ev.camera_name || 'Camera Source'} {ev.camera_location ? `(${ev.camera_location})` : ''}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Date / Time */}
                      <td className="px-6 py-4 text-xs font-mono text-slate-500 whitespace-nowrap">
                        <span className="flex items-center space-x-1.5">
                          <Calendar className="h-3.5 w-3.5 text-slate-400" />
                          <span>Time: {new Date(ev.timestamp).toLocaleString()}</span>
                        </span>
                      </td>

                      {/* Confidence */}
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`text-[10px] font-bold px-2.5 py-1 rounded-full border font-mono uppercase ${
                          ev.confidence === 'high' || (ev.confidence_score && ev.confidence_score >= 0.70)
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            : 'bg-amber-50 text-amber-700 border-amber-200'
                        }`}>
                          {ev.confidence_score ? `${(ev.confidence_score * 100).toFixed(0)}% High Conf.` : `${ev.confidence} Conf.`}
                        </span>
                      </td>

                      {/* Target Identity & Persons Identified Count */}
                      <td className="px-6 py-4">
                        <div className="space-y-1">
                          <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-900">
                            <Users className="h-3.5 w-3.5 text-blue-600" />
                            <span>
                              Persons identified: {ev.persons_identified_count ?? (ev.students && ev.students.length > 0 ? ev.students.length : (ev.student_name ? 1 : 0))}
                            </span>
                          </div>
                          {ev.students && ev.students.length > 0 ? (
                            <div className="text-[11px] text-emerald-700 font-medium truncate max-w-xs">
                              {ev.students.map((s: any) => s.name).join(', ')}
                            </div>
                          ) : ev.student_name ? (
                            <div className="text-[11px] text-emerald-700 font-medium">
                              {ev.student_name}
                            </div>
                          ) : (
                            <div className="text-[10px] text-slate-400 italic">
                              Unidentified
                            </div>
                          )}
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="px-6 py-4 text-right whitespace-nowrap">
                        <div className="flex items-center justify-end space-x-2">
                          <Link
                            to={`/events/${ev.id}`}
                            className="inline-flex items-center space-x-1.5 text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white px-3.5 py-2 rounded-xl shadow-xs transition"
                          >
                            <Eye className="h-3.5 w-3.5" />
                            <span>View Alert</span>
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={5} className="text-center py-16 text-slate-400">
                    No surveillance alert events recorded for this category.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Events;
