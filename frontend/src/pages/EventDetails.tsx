import React from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { ShieldAlert, ArrowLeft, Video, User, AlertCircle, Eye, Calendar, MapPin, CheckCircle2 } from 'lucide-react';

export const EventDetails: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data: event, isLoading: isEventLoading } = useQuery({
    queryKey: ['event-detail', id],
    queryFn: async () => {
      const response = await api.get(`/events/${id}`);
      return response.data;
    }
  });

  const { data: camera } = useQuery({
    queryKey: ['camera-detail', event?.camera_id],
    queryFn: async () => {
      const response = await api.get(`/cameras/${event.camera_id}`);
      return response.data;
    },
    enabled: !!event?.camera_id
  });

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  if (isEventLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <p className="animate-pulse font-semibold text-sm">Loading security alert dossier...</p>
      </div>
    );
  }

  const eventTypeLabel = event?.event_type?.replace(/_/g, ' ') || 'Security Alert';

  return (
    <div className="space-y-8 py-2">
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate('/events')}
          className="flex items-center space-x-2 text-slate-400 hover:text-slate-200 transition text-sm font-semibold"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Security Alerts Log</span>
        </button>
      </div>

      <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md flex items-center justify-between">
        <div className="flex items-center space-x-5">
          <div className="bg-red-500/10 p-4 rounded-xl border border-red-500/20">
            <ShieldAlert className="h-8 w-8 text-red-500" />
          </div>
          <div>
            <h2 className="text-2xl font-bold text-slate-100 uppercase tracking-wide">
              {eventTypeLabel} Alert
            </h2>
            <p className="text-slate-400 text-xs mt-0.5 font-mono">Alert Incident UUID: {event?.id}</p>
          </div>
        </div>
        <span className={`text-xs font-bold px-3 py-1 rounded-full border uppercase font-mono ${
          event?.confidence === 'high'
            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
            : 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20'
        }`}>
          {event?.confidence_score ? `${(event.confidence_score * 100).toFixed(0)}% Confidence` : `${event?.confidence} Confidence`}
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left 2 Columns - Media Visuals & Explanation */}
        <div className="lg:col-span-2 space-y-6">
          {/* Explanation Banner */}
          {event?.explanation && (
            <div className="bg-slate-900/60 border border-dark-border p-5 rounded-2xl space-y-2">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 font-mono">
                Anomaly Explanation & Trigger Report
              </span>
              <p className="text-sm text-slate-200 font-medium leading-relaxed">
                "{event.explanation}"
              </p>
            </div>
          )}

          {/* Video Sub-clip Recording */}
          {event?.evidence_video && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <div className="flex items-center space-x-2 text-slate-200 font-bold text-sm">
                <Video className="h-4 w-4 text-blue-500" />
                <span>Recorded Anomaly Video Clip</span>
              </div>
              <div className="rounded-xl overflow-hidden bg-slate-950 border border-dark-border">
                <video
                  src={`${API_URL}${event.evidence_video}`}
                  controls
                  autoPlay
                  className="w-full max-h-96 object-contain"
                />
              </div>
            </div>
          )}

          {/* Screenshot Frame Crop */}
          {event?.evidence_image && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <div className="flex items-center space-x-2 text-slate-200 font-bold text-sm">
                <Eye className="h-4 w-4 text-purple-400" />
                <span>Subject Frame Screenshot Crop</span>
              </div>
              <div className="rounded-xl overflow-hidden bg-slate-950 border border-dark-border flex justify-center p-2">
                <img
                  src={`${API_URL}${event.evidence_image}`}
                  alt="Anomaly Crop"
                  className="max-h-72 object-contain rounded-lg"
                  onError={(e: any) => { e.target.src = '/storage/crops/simulated_face.jpg'; }}
                />
              </div>
            </div>
          )}
        </div>

        {/* Right Column - Incident Details & Engaged Students */}
        <div className="space-y-6">
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <h3 className="font-bold text-slate-200 text-lg">Alert Metadata</h3>
            <div className="space-y-4 text-sm divide-y divide-dark-border/50">
              <div className="flex justify-between py-2 first:pt-0">
                <span className="text-slate-500">Camera Source</span>
                <span className="font-semibold text-slate-200">
                  {event?.camera_name || camera?.name || event?.camera_id?.slice(0, 8)}
                </span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-slate-500">Camera Location</span>
                <span className="font-semibold text-slate-200">
                  {event?.camera_location || camera?.location || 'Campus Zone'}
                </span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-slate-500">Date & Time</span>
                <span className="font-semibold text-slate-200 font-mono text-xs">
                  {event && new Date(event.timestamp).toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between py-2 last:pb-0">
                <span className="text-slate-500">Alert Category</span>
                <span className="text-xs font-bold text-red-400 uppercase font-mono">
                  {eventTypeLabel}
                </span>
              </div>
            </div>
          </div>

          {/* Target Identification / Engaged Students */}
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <h3 className="font-bold text-slate-200 text-lg">Target Identification</h3>
            {event?.students && event.students.length > 0 ? (
              <div className="space-y-3">
                {event.students.map((std: any, idx: number) => (
                  <div key={idx} className="bg-slate-900/60 p-4 rounded-xl border border-dark-border space-y-3">
                    <div className="flex justify-between items-center border-b border-dark-border/40 pb-2">
                      <div className="flex items-center space-x-2">
                        <User className="h-4 w-4 text-blue-400" />
                        <span className="font-bold text-slate-200 text-sm">{std.name}</span>
                      </div>
                      <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 font-mono font-semibold">
                        Identified
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs font-mono text-slate-400">
                      <div>
                        <span className="text-[9px] text-slate-500 block">Roll Number</span>
                        <span className="text-slate-200 font-bold">{std.roll_number}</span>
                      </div>
                      <div>
                        <span className="text-[9px] text-slate-500 block">Class</span>
                        <span className="text-slate-200 font-bold">{std.class}</span>
                      </div>
                    </div>
                    {std.id && (
                      <Link
                        to={`/students/${std.id}`}
                        className="block text-center py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg text-xs font-semibold transition"
                      >
                        View Full Student Profile
                      </Link>
                    )}
                  </div>
                ))}
              </div>
            ) : event?.student_name ? (
              <div className="space-y-3">
                <div className="bg-slate-900/60 p-4 rounded-xl border border-dark-border space-y-3">
                  <div className="flex justify-between items-center border-b border-dark-border/40 pb-2">
                    <div className="flex items-center space-x-2">
                      <User className="h-4 w-4 text-blue-400" />
                      <span className="font-bold text-slate-200 text-sm">{event.student_name}</span>
                    </div>
                    <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 font-mono font-semibold">
                      Identified
                    </span>
                  </div>
                  <div className="text-xs font-mono text-slate-400">
                    <span className="text-[9px] text-slate-500 block">Roll Number</span>
                    <span className="text-slate-200 font-bold">{event.student_roll || 'N/A'}</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="bg-slate-900/50 p-4 rounded-xl border border-dark-border flex items-start space-x-3 text-slate-400 text-xs">
                <AlertCircle className="h-5 w-5 text-slate-500 flex-shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold text-slate-300 block">Unknown Target Profile</span>
                  <p className="text-slate-500 mt-1">
                    No face enrollment matches resolved for the subject(s) in this alert event.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default EventDetails;
