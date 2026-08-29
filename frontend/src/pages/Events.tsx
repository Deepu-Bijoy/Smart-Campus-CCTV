import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { 
  ShieldAlert, 
  Calendar, 
  Eye, 
  Activity, 
  AlertCircle, 
  Video, 
  User, 
  X, 
  ExternalLink,
  Filter,
  CheckCircle2,
  AlertTriangle,
  Swords,
  Footprints,
  Lock
} from 'lucide-react';
import { Link } from 'react-router-dom';

export const Events: React.FC = () => {
  const [selectedFilter, setSelectedFilter] = useState<string>('ALL');
  const [activeModalAlert, setActiveModalAlert] = useState<any | null>(null);

  const { data: events, isLoading } = useQuery({
    queryKey: ['events-list'],
    queryFn: async () => {
      const response = await api.get('/events');
      return response.data || [];
    }
  });

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  // Filter events based on active category tab
  const filteredEvents = React.useMemo(() => {
    if (!events) return [];
    if (selectedFilter === 'ALL') return events;
    return events.filter((ev: any) => {
      const type = (ev.event_type || '').toUpperCase();
      if (selectedFilter === 'FIGHT') return type.includes('FIGHT');
      if (selectedFilter === 'BOUNDARY') return type.includes('FENCE') || type.includes('BOUNDARY') || type.includes('JUMP');
      if (selectedFilter === 'RESTRICTED') return type.includes('RESTRICTED') || type.includes('ENTRY');
      if (selectedFilter === 'SUSPICIOUS') return type.includes('SUSPICIOUS') || type.includes('ANOMALY');
      return true;
    });
  }, [events, selectedFilter]);

  const getEventBadgeClass = (typeStr: string) => {
    const type = (typeStr || '').toUpperCase();
    if (type.includes('FIGHT')) {
      return {
        badge: 'bg-red-500/10 text-red-400 border-red-500/30',
        icon: <Swords className="h-4 w-4 text-red-500" />,
        label: 'Fight / Altercation'
      };
    } else if (type.includes('FENCE') || type.includes('BOUNDARY') || type.includes('JUMP')) {
      return {
        badge: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
        icon: <Footprints className="h-4 w-4 text-amber-500" />,
        label: 'Boundary / Fence Jump'
      };
    } else if (type.includes('RESTRICTED') || type.includes('ENTRY')) {
      return {
        badge: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
        icon: <Lock className="h-4 w-4 text-purple-400" />,
        label: 'Restricted Area Entry'
      };
    } else {
      return {
        badge: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30',
        icon: <AlertTriangle className="h-4 w-4 text-yellow-400" />,
        label: 'Suspicious Activity'
      };
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <p className="animate-pulse font-semibold text-sm">Loading real-time surveillance alerts...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 py-2">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-100">Security Alerts Log</h2>
          <p className="text-slate-400 text-sm">Real-time surveillance triggers: Fights, fence jumps, boundary crossings, and unauthorized entries</p>
        </div>

        {/* Total count indicator */}
        <div className="flex items-center space-x-2 bg-dark-card border border-dark-border px-4 py-2 rounded-xl text-xs font-mono">
          <span className="text-slate-400">Total Recorded Alerts:</span>
          <span className="font-bold text-blue-400 text-sm">{events?.length || 0}</span>
        </div>
      </div>

      {/* Category Filter Tabs */}
      <div className="flex flex-wrap gap-2 bg-slate-900/40 p-2 rounded-2xl border border-dark-border">
        {[
          { id: 'ALL', label: 'All Alerts', icon: <ShieldAlert className="h-3.5 w-3.5" /> },
          { id: 'FIGHT', label: 'Fights & Altercations', icon: <Swords className="h-3.5 w-3.5 text-red-400" /> },
          { id: 'BOUNDARY', label: 'Fence Jumps & Boundary', icon: <Footprints className="h-3.5 w-3.5 text-amber-400" /> },
          { id: 'RESTRICTED', label: 'Restricted Area Entries', icon: <Lock className="h-3.5 w-3.5 text-purple-400" /> },
          { id: 'SUSPICIOUS', label: 'Suspicious Activities', icon: <AlertTriangle className="h-3.5 w-3.5 text-yellow-400" /> },
        ].map((tab) => {
          const isActive = selectedFilter === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setSelectedFilter(tab.id)}
              className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
                isActive
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Alerts Table */}
      <div className="bg-dark-card border border-dark-border rounded-2xl overflow-hidden shadow-lg">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-dark-border text-xs font-semibold text-slate-400 bg-slate-900/50">
                <th className="px-6 py-4">Event Type / Camera</th>
                <th className="px-6 py-4">Date / Time</th>
                <th className="px-6 py-4">Confidence</th>
                <th className="px-6 py-4">Target Identity (Engaged Students)</th>
                <th className="px-6 py-4 text-right">Actions & Inspection</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border text-sm text-slate-300">
              {filteredEvents && filteredEvents.length > 0 ? (
                filteredEvents.map((ev: any) => {
                  const badgeInfo = getEventBadgeClass(ev.event_type);
                  return (
                    <tr key={ev.id} className="hover:bg-slate-900/40 transition">
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
                            <span className="font-semibold text-slate-200 block text-xs">
                              {ev.camera_name || 'Camera Source'} {ev.camera_location ? `(${ev.camera_location})` : ''}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Date / Time */}
                      <td className="px-6 py-4 text-xs font-mono text-slate-400 whitespace-nowrap">
                        <span className="flex items-center space-x-1.5">
                          <Calendar className="h-3.5 w-3.5 text-slate-500" />
                          <span>{new Date(ev.timestamp).toLocaleString()}</span>
                        </span>
                      </td>

                      {/* Confidence */}
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`text-[10px] font-bold px-2.5 py-1 rounded-full border font-mono uppercase ${
                          ev.confidence === 'high' || (ev.confidence_score && ev.confidence_score >= 0.70)
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                            : 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20'
                        }`}>
                          {ev.confidence_score ? `${(ev.confidence_score * 100).toFixed(0)}% High Conf.` : `${ev.confidence} Conf.`}
                        </span>
                      </td>

                      {/* Target Identity */}
                      <td className="px-6 py-4">
                        {ev.students && ev.students.length > 0 ? (
                          <div className="space-y-1">
                            <div className="flex items-center space-x-1.5 text-xs text-emerald-400 font-semibold">
                              <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
                              <span>{ev.students.map((s: any) => s.name).join(', ')}</span>
                            </div>
                            <span className="text-[10px] text-slate-500 font-mono block">
                              Roll: {ev.students.map((s: any) => s.roll_number).join(', ')} (Directory Matched)
                            </span>
                          </div>
                        ) : ev.student_name ? (
                          <div className="space-y-1">
                            <div className="flex items-center space-x-1.5 text-xs text-emerald-400 font-semibold">
                              <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
                              <span>{ev.student_name}</span>
                            </div>
                            <span className="text-[10px] text-slate-500 font-mono block">
                              Roll: {ev.student_roll || 'N/A'} (Directory Matched)
                            </span>
                          </div>
                        ) : (
                          <div className="flex items-center space-x-1.5 text-xs text-slate-500">
                            <AlertCircle className="h-3.5 w-3.5 flex-shrink-0 text-slate-500" />
                            <span>Unknown Target Profile</span>
                          </div>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="px-6 py-4 text-right whitespace-nowrap">
                        <div className="flex items-center justify-end space-x-2">
                          <button
                            onClick={() => setActiveModalAlert(ev)}
                            className="inline-flex items-center space-x-1.5 text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white px-3.5 py-2 rounded-xl shadow-md shadow-blue-500/20 transition cursor-pointer"
                          >
                            <Eye className="h-3.5 w-3.5" />
                            <span>Analyze Alert</span>
                          </button>
                          <Link
                            to={`/events/${ev.id}`}
                            className="p-2 text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 rounded-xl transition border border-dark-border"
                            title="View Detailed Dossier"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={5} className="text-center py-16 text-slate-500">
                    No surveillance alert events recorded for this category.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Alert Inspection & Media Modal */}
      {activeModalAlert && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-dark-card border border-dark-border rounded-2xl max-w-3xl w-full max-h-[90vh] overflow-y-auto shadow-2xl space-y-6 p-6 relative">
            {/* Close Button */}
            <button
              onClick={() => setActiveModalAlert(null)}
              className="absolute top-5 right-5 text-slate-400 hover:text-slate-100 p-2 rounded-xl bg-slate-800/60 hover:bg-slate-800 border border-dark-border transition"
            >
              <X className="h-5 w-5" />
            </button>

            {/* Modal Header */}
            <div className="flex items-center space-x-4 border-b border-dark-border pb-4">
              <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-xl">
                <ShieldAlert className="h-6 w-6 text-red-500" />
              </div>
              <div>
                <div className="flex items-center space-x-2">
                  <h3 className="text-lg font-bold text-slate-100 uppercase tracking-wide">
                    {activeModalAlert.event_type?.replace(/_/g, ' ')} Alert Forensic Inspection
                  </h3>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                    VERIFIED ANOMALY
                  </span>
                </div>
                <p className="text-xs text-slate-400 font-mono mt-0.5">
                  Camera: {activeModalAlert.camera_name} ({activeModalAlert.camera_location}) | {new Date(activeModalAlert.timestamp).toLocaleString()}
                </p>
              </div>
            </div>

            {/* Explanation Summary */}
            {activeModalAlert.explanation && (
              <div className="bg-slate-900/60 border border-dark-border p-4 rounded-xl space-y-1 text-xs">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 font-mono">
                  Trigger Reason & Explanation
                </span>
                <p className="text-slate-200 italic leading-relaxed">
                  "{activeModalAlert.explanation}"
                </p>
              </div>
            )}

            {/* Visual Media Section (Video & Screenshot) */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Video sub-clip */}
              {activeModalAlert.evidence_video && (
                <div className="space-y-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 font-mono flex items-center space-x-1">
                    <Video className="h-3.5 w-3.5 text-blue-400" />
                    <span>Recorded Video Clip</span>
                  </span>
                  <div className="border border-dark-border rounded-xl overflow-hidden bg-slate-950">
                    <video
                      src={`${API_URL}${activeModalAlert.evidence_video}`}
                      controls
                      autoPlay
                      className="w-full max-h-56 object-contain"
                    />
                  </div>
                </div>
              )}

              {/* Screenshot Frame Crop */}
              {activeModalAlert.evidence_image && (
                <div className="space-y-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 font-mono flex items-center space-x-1">
                    <Eye className="h-3.5 w-3.5 text-purple-400" />
                    <span>Frame Screenshot Crop</span>
                  </span>
                  <div className="border border-dark-border rounded-xl overflow-hidden bg-slate-950 flex justify-center p-1">
                    <img
                      src={`${API_URL}${activeModalAlert.evidence_image}`}
                      alt="Alert Screenshot"
                      className="max-h-56 object-contain rounded-lg"
                      onError={(e: any) => { e.target.src = '/storage/crops/simulated_face.jpg'; }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Engaged Student Profiles */}
            <div className="space-y-3 pt-2 border-t border-dark-border">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 font-mono block">
                Engaged Student Profiles (Student Directory Match)
              </span>
              {activeModalAlert.students && activeModalAlert.students.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {activeModalAlert.students.map((std: any, sIdx: number) => (
                    <div key={sIdx} className="bg-slate-900/50 border border-dark-border p-3.5 rounded-xl space-y-2">
                      <div className="flex justify-between items-center border-b border-dark-border/40 pb-2">
                        <div className="flex items-center space-x-2">
                          <User className="h-4 w-4 text-blue-400" />
                          <span className="text-xs font-bold text-slate-200">{std.name}</span>
                        </div>
                        <span className="text-[9px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 font-mono font-semibold">
                          Directory Matched
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-[11px] font-mono text-slate-400">
                        <div>
                          <span className="text-[9px] text-slate-500 block">Roll Number</span>
                          <span className="text-slate-200 font-bold">{std.roll_number}</span>
                        </div>
                        <div>
                          <span className="text-[9px] text-slate-500 block">Class</span>
                          <span className="text-slate-200 font-bold">{std.class}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : activeModalAlert.student_name ? (
                <div className="bg-slate-900/50 border border-dark-border p-3.5 rounded-xl space-y-2 max-w-sm">
                  <div className="flex justify-between items-center border-b border-dark-border/40 pb-2">
                    <div className="flex items-center space-x-2">
                      <User className="h-4 w-4 text-blue-400" />
                      <span className="text-xs font-bold text-slate-200">{activeModalAlert.student_name}</span>
                    </div>
                    <span className="text-[9px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 font-mono font-semibold">
                      Directory Matched
                    </span>
                  </div>
                  <div className="text-[11px] font-mono text-slate-400">
                    <span className="text-[9px] text-slate-500 block">Roll Number</span>
                    <span className="text-slate-200 font-bold">{activeModalAlert.student_roll || 'N/A'}</span>
                  </div>
                </div>
              ) : (
                <div className="text-center py-4 bg-slate-900/30 border border-dashed border-dark-border text-xs text-slate-500 rounded-xl">
                  No face enrollment matches resolved in student directory for this event (Unknown Target).
                </div>
              )}
            </div>

            {/* Footer Action */}
            <div className="flex justify-end pt-2">
              <Link
                to={`/events/${activeModalAlert.id}`}
                className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-5 py-2.5 rounded-xl shadow-lg transition flex items-center space-x-2"
              >
                <span>Open Full Incident Dossier Page</span>
                <ExternalLink className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Events;
