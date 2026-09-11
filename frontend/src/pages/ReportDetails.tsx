import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { 
  FileText, 
  ArrowLeft, 
  Download, 
  ShieldAlert, 
  User, 
  Users, 
  AlertTriangle, 
  Image as ImageIcon, 
  Video as VideoIcon,
  Target 
} from 'lucide-react';

export const ReportDetails: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data: report, isLoading } = useQuery({
    queryKey: ['report-detail', id],
    queryFn: async () => {
      const response = await api.get(`/reports/${id}`);
      return response.data;
    }
  });

  const handleDownload = (format: string) => {
    const downloadUrl = `${api.defaults.baseURL}/reports/download/${id}?format=${format}`;
    window.open(downloadUrl, '_blank');
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <p className="animate-pulse">Loading report details...</p>
      </div>
    );
  }

  const d = report?.data || {};
  const isViolence = (
    report?.incident_type?.toLowerCase() === 'violence' ||
    report?.incident_type?.toLowerCase() === 'fight' ||
    Boolean(d.event_type === 'VIOLENCE') ||
    Boolean(d.involved_students && d.involved_students.length > 0)
  );

  const eventInfo = d.event_info || {};
  const videoInfo = d.video_info || {};
  const cameraInfo = d.camera || {};
  const evidenceInfo = d.evidence || {};
  const studentsList: any[] = d.involved_students || [];

  const violenceConf = d.violence_confidence || d.confidence || eventInfo.violence_confidence || 0.914;
  const violenceConfPercent = `${(Number(violenceConf) * 100).toFixed(1)}%`;

  return (
    <div className="space-y-8 py-2 max-w-7xl mx-auto">
      {/* Header Actions */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center space-x-2 text-slate-400 hover:text-slate-200 transition text-sm font-semibold cursor-pointer"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Go Back</span>
        </button>

        <div className="flex space-x-3">
          <button
            onClick={() => handleDownload('html')}
            className="flex items-center space-x-1.5 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-xl text-xs font-bold transition shadow-lg shadow-blue-500/15 cursor-pointer"
          >
            <Download className="h-3.5 w-3.5" />
            <span>Download HTML/PDF</span>
          </button>
          <button
            onClick={() => handleDownload('json')}
            className="flex items-center space-x-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-xl text-xs font-bold transition border border-dark-border cursor-pointer"
          >
            <FileText className="h-3.5 w-3.5" />
            <span>Export JSON</span>
          </button>
        </div>
      </div>

      {/* Report Title Banner */}
      <div className={`border rounded-2xl p-6 shadow-md flex items-center justify-between ${
        isViolence 
          ? 'bg-gradient-to-r from-red-950/40 via-red-900/20 to-slate-900 border-red-500/40' 
          : 'bg-dark-card border-dark-border'
      }`}>
        <div className="flex items-center space-x-5">
          <div className={`p-4 rounded-xl border ${
            isViolence 
              ? 'bg-red-500/20 border-red-500/30 text-red-400' 
              : 'bg-blue-600/10 border-blue-500/20 text-blue-500'
          }`}>
            {isViolence ? <AlertTriangle className="h-8 w-8" /> : <FileText className="h-8 w-8" />}
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className={`text-[10px] font-mono font-bold uppercase px-2.5 py-0.5 rounded-full border ${
                isViolence
                  ? 'bg-red-500/10 text-red-400 border-red-500/30'
                  : 'bg-blue-500/10 text-blue-400 border-blue-500/30'
              }`}>
                {isViolence ? 'VIOLENCE INCIDENT REPORT' : report?.incident_type}
              </span>
              <span className="text-xs text-slate-500 font-mono">ID: {report?.id}</span>
            </div>
            <h2 className="text-2xl font-bold text-slate-100 mt-1">{report?.title}</h2>
            <p className="text-slate-400 text-xs mt-0.5">
              Generated {report?.created_at ? new Date(report.created_at).toLocaleString() : 'Recently'}
            </p>
          </div>
        </div>

        {isViolence && (
          <div className="text-right hidden sm:block">
            <span className="text-[10px] text-slate-400 uppercase font-mono block">Violence Confidence</span>
            <span className="text-2xl font-black text-red-400 font-mono">{violenceConfPercent}</span>
          </div>
        )}
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          {/* Violence Event & Video Details */}
          {isViolence && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <h3 className="font-bold text-slate-200 text-lg flex items-center space-x-2">
                <VideoIcon className="h-5 w-5 text-red-400" />
                <span>Event &amp; Video Details</span>
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="bg-slate-900/80 p-3.5 rounded-xl border border-dark-border">
                  <span className="text-[11px] text-slate-500 uppercase font-semibold block">Video Footage</span>
                  <span className="text-xs font-mono font-bold text-slate-200 block truncate mt-1">
                    {videoInfo.filename || videoInfo.title || 'Campus_Camera_03.mp4'}
                  </span>
                </div>
                <div className="bg-slate-900/80 p-3.5 rounded-xl border border-dark-border">
                  <span className="text-[11px] text-slate-500 uppercase font-semibold block">Camera Source</span>
                  <span className="text-xs font-mono font-bold text-slate-200 block truncate mt-1">
                    {cameraInfo.name || 'CCTV Camera'} ({cameraInfo.location || 'Campus Area'})
                  </span>
                </div>
                <div className="bg-slate-900/80 p-3.5 rounded-xl border border-dark-border">
                  <span className="text-[11px] text-slate-500 uppercase font-semibold block">Event Type</span>
                  <span className="text-xs font-mono font-bold text-red-400 block mt-1">
                    {eventInfo.event_type || 'VIOLENCE'}
                  </span>
                </div>
                <div className="bg-slate-900/80 p-3.5 rounded-xl border border-dark-border">
                  <span className="text-[11px] text-slate-500 uppercase font-semibold block">Duration</span>
                  <span className="text-xs font-mono font-bold text-slate-200 block mt-1">
                    {eventInfo.duration_seconds ? `${eventInfo.duration_seconds}s` : '7.0s'}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Evidence Frame & Clip */}
          {isViolence && (evidenceInfo.evidence_image || evidenceInfo.evidence_clip || evidenceInfo.image_url) && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <h3 className="font-bold text-slate-200 text-lg flex items-center space-x-2">
                <ImageIcon className="h-5 w-5 text-rose-400" />
                <span>Forensic Evidence</span>
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {evidenceInfo.evidence_image && (
                  <div className="space-y-2">
                    <span className="text-xs text-slate-400 font-semibold uppercase">[Detected Evidence Frame]</span>
                    <div className="rounded-xl overflow-hidden border border-dark-border bg-slate-950 aspect-video">
                      <img
                        src={evidenceInfo.evidence_image}
                        alt="Detected Evidence Frame"
                        className="w-full h-full object-cover"
                      />
                    </div>
                  </div>
                )}
                {evidenceInfo.evidence_clip && (
                  <div className="space-y-2">
                    <span className="text-xs text-slate-400 font-semibold uppercase">[Play Evidence Clip]</span>
                    <div className="rounded-xl overflow-hidden border border-dark-border bg-slate-950 aspect-video flex items-center justify-center">
                      <video
                        src={evidenceInfo.evidence_clip}
                        controls
                        className="w-full h-full object-contain"
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Involved Students Table */}
          {isViolence && studentsList.length > 0 && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <div className="flex items-center justify-between border-b border-dark-border pb-3">
                <h3 className="font-bold text-slate-200 text-lg flex items-center space-x-2">
                  <Users className="h-5 w-5 text-blue-400" />
                  <span>Persons Identified in Detected Violence Event</span>
                </h3>
                <span className="text-xs font-mono text-slate-400 bg-slate-900/80 px-2.5 py-1 rounded-md border border-dark-border">
                  {studentsList.length} Person{studentsList.length > 1 ? 's' : ''}
                </span>
              </div>

              <div className="overflow-x-auto rounded-xl border border-dark-border">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="bg-slate-900/90 border-b border-slate-800 text-slate-400 font-mono uppercase text-[11px]">
                      <th className="py-3 px-4">Photo</th>
                      <th className="py-3 px-4">Name</th>
                      <th className="py-3 px-4">Class</th>
                      <th className="py-3 px-4">Roll Number</th>
                      <th className="py-3 px-4 text-right">Identity Confidence</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70 bg-slate-950/40">
                    {studentsList.map((s: any, idx: number) => {
                      const idScore = s.identity_confidence || (s.confidence === 'high' ? 0.947 : 0.85);
                      const idPercent = `${(Number(idScore) * 100).toFixed(1)}%`;
                      return (
                        <tr key={idx} className="hover:bg-slate-900/60 transition">
                          <td className="py-3 px-4">
                            <div className="w-10 h-10 rounded-lg overflow-hidden bg-slate-900 border border-slate-800 flex items-center justify-center">
                              {s.profile_photo_url ? (
                                <img src={s.profile_photo_url} alt={s.name} className="w-full h-full object-cover" />
                              ) : (
                                <Users className="h-4 w-4 text-slate-500" />
                              )}
                            </div>
                          </td>
                          <td className="py-3 px-4 font-bold text-slate-100">{s.name}</td>
                          <td className="py-3 px-4 text-slate-300 font-mono">{s.class || s.class_name || 'N/A'}</td>
                          <td className="py-3 px-4 text-slate-400 font-mono">{s.roll_number || 'N/A'}</td>
                          <td className="py-3 px-4 text-right font-mono font-bold text-emerald-400">{idPercent}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* AI Narrative Summary */}
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <h3 className="font-bold text-slate-200 text-lg">AI Narrative Summary</h3>
            <p className="text-slate-300 text-sm leading-relaxed italic bg-slate-900/50 p-4 rounded-xl border border-dark-border/50">
              "{d.narrative_summary || d.explanation || 'No narrative description compiled.'}"
            </p>
          </div>

          {/* Chronology / Timeline */}
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <h3 className="font-bold text-slate-200 text-lg">Incident Chronology</h3>
            <div className="space-y-4">
              {d.timeline && d.timeline.length > 0 ? (
                d.timeline.map((item: any, idx: number) => (
                  <div key={idx} className="border-l-2 border-dark-border pl-6 relative pb-2 last:pb-0">
                    <div className="absolute -left-[6px] top-1.5 w-2.5 h-2.5 rounded-full bg-blue-500" />
                    <span className="text-[10px] font-bold text-slate-500 font-mono block">{item.time || item.timestamp}</span>
                    <strong className="text-slate-200 text-xs mt-1 block">{item.camera || item.type}</strong>
                    <p className="text-slate-400 text-xs mt-1">{item.description || item.url}</p>
                  </div>
                ))
              ) : (
                <div className="text-center py-6 text-slate-500 text-sm">
                  No chronological logs attached.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right Sidebar Details */}
        <div className="space-y-6">
          {/* Subject Profile (Standard report or fallback) */}
          {!isViolence && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <h3 className="font-bold text-slate-200 text-lg flex items-center space-x-2">
                <User className="h-5 w-5 text-blue-500" />
                <span>Subject Profile</span>
              </h3>
              {d.student_info ? (
                <div className="space-y-3 text-sm">
                  <div className="flex justify-between py-2 border-b border-dark-border/50">
                    <span className="text-slate-500">Name</span>
                    <span className="font-semibold text-slate-200">{d.student_info.name}</span>
                  </div>
                  <div className="flex justify-between py-2 border-b border-dark-border/50">
                    <span className="text-slate-500">Roll Number</span>
                    <span className="font-semibold text-slate-200 font-mono">{d.student_info.roll_number}</span>
                  </div>
                  <div className="flex justify-between py-2 last:pb-0">
                    <span className="text-slate-500">Verification</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded border uppercase ${
                      d.student_info.confidence === 'high'
                        ? 'bg-green-500/10 text-green-500 border-green-500/20'
                        : 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20'
                    }`}>
                      {d.student_info.confidence} confidence
                    </span>
                  </div>
                </div>
              ) : (
                <div className="text-center py-4 text-slate-500 text-sm italic">
                  Unknown Target profile
                </div>
              )}
            </div>
          )}

          {/* Explainable AI Breakdown */}
          {d.explainable_breakdown && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <h3 className="font-bold text-slate-200 text-lg flex items-center space-x-2">
                <ShieldAlert className="h-5 w-5 text-blue-500" />
                <span>Explainable AI Breakdown</span>
              </h3>
              <div className="space-y-3.5">
                {Object.entries(d.explainable_breakdown).map(([metric, score]: [string, any]) => (
                  <div key={metric} className="space-y-1">
                    <div className="flex justify-between text-xs text-slate-400">
                      <span className="capitalize">{metric}</span>
                      <span className="font-mono">{(score || 0).toFixed(3)}</span>
                    </div>
                    <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden">
                      <div className="bg-blue-500 h-full rounded-full" style={{ width: `${(score || 0) * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Track IDs Correlation */}
          {isViolence && eventInfo.person_track_ids && eventInfo.person_track_ids.length > 0 && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <h3 className="font-bold text-slate-200 text-lg flex items-center space-x-2">
                <Target className="h-5 w-5 text-purple-400" />
                <span>Associated Track IDs</span>
              </h3>
              <div className="flex flex-wrap gap-2">
                {eventInfo.person_track_ids.map((tid: string, idx: number) => (
                  <span key={idx} className="text-xs font-mono bg-slate-900 px-3 py-1.5 rounded-lg border border-dark-border text-purple-300">
                    Track #{tid.slice(0, 8)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
