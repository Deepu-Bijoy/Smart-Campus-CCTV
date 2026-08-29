import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { FileText, ArrowLeft, Download, ShieldAlert, User } from 'lucide-react';

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

  return (
    <div className="space-y-8 py-2">
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center space-x-2 text-slate-400 hover:text-slate-200 transition text-sm font-semibold"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Go Back</span>
        </button>

        <div className="flex space-x-3">
          <button
            onClick={() => handleDownload('html')}
            className="flex items-center space-x-1.5 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-xl text-xs font-bold transition shadow-lg shadow-blue-500/15"
          >
            <Download className="h-3.5 w-3.5" />
            <span>Download HTML/PDF</span>
          </button>
          <button
            onClick={() => handleDownload('json')}
            className="flex items-center space-x-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-xl text-xs font-bold transition border border-dark-border"
          >
            <FileText className="h-3.5 w-3.5" />
            <span>Export JSON</span>
          </button>
        </div>
      </div>

      <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md flex items-center space-x-5">
        <div className="bg-blue-600/10 p-4 rounded-xl border border-blue-500/20">
          <FileText className="h-8 w-8 text-blue-500" />
        </div>
        <div>
          <h2 className="text-2xl font-bold text-slate-100">{report?.title}</h2>
          <p className="text-slate-400 text-xs mt-0.5">Classification: {report?.incident_type}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <h3 className="font-bold text-slate-200 text-lg">AI Narrative Summary</h3>
            <p className="text-slate-300 text-sm leading-relaxed italic bg-slate-900/50 p-4 rounded-xl border border-dark-border/50">
              "{d.narrative_summary || 'No narrative description generated.'}"
            </p>
          </div>

          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <h3 className="font-bold text-slate-200 text-lg">Incident Chronology</h3>
            <div className="space-y-4">
              {d.timeline && d.timeline.length > 0 ? (
                d.timeline.map((item: any, idx: number) => (
                  <div key={idx} className="border-l-2 border-dark-border pl-6 relative pb-2 last:pb-0">
                    <div className="absolute -left-[6px] top-1.5 w-2.5 h-2.5 rounded-full bg-blue-500" />
                    <span className="text-[10px] font-bold text-slate-500 font-mono block">{item.time}</span>
                    <strong className="text-slate-200 text-xs mt-1 block">{item.camera}</strong>
                    <p className="text-slate-400 text-xs mt-1">{item.description}</p>
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

        <div className="space-y-6">
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

          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <h3 className="font-bold text-slate-200 text-lg flex items-center space-x-2">
              <ShieldAlert className="h-5 w-5 text-blue-500" />
              <span>Explainable AI Breakdown</span>
            </h3>
            <div className="space-y-3.5">
              {d.explainable_breakdown && Object.entries(d.explainable_breakdown).map(([metric, score]: [string, any]) => (
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
        </div>
      </div>
    </div>
  );
};
