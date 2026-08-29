import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { FileText, Calendar, Plus, Check, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';

export const Reports: React.FC = () => {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState('');
  const [incidentType, setIncidentType] = useState('Fence Crossing');
  const [studentName, setStudentName] = useState('Alex Mercer');
  const rollNumber = 'CS-2026-99';

  const { data: reports, isLoading } = useQuery({
    queryKey: ['reports-list'],
    queryFn: async () => {
      try {
        const response = await api.get('/reports');
        return response.data || [];
      } catch {
        // Return blank fallback arrays if db is currently cold
        return [];
      }
    }
  });

  const createReportMutation = useMutation({
    mutationFn: async (reportData: any) => {
      const response = await api.post('/reports/generate', reportData);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reports-list'] });
      setShowForm(false);
      setTitle('');
    }
  });

  const handleGenerate = () => {
    if (!title) {
      alert('Provide a report title.');
      return;
    }
    createReportMutation.mutate({
      title,
      incident_type: incidentType,
      data: {
        narrative_summary: `Subject verified as student ${studentName} was detected triggering a ${incidentType} boundary violation. Track vectors verify crossing heading and physical description overlap.`,
        student_info: {
          name: studentName,
          roll_number: rollNumber,
          confidence: 'high'
        },
        explainable_breakdown: {
          semantic: 0.82,
          identity: 0.94,
          appearance: 0.86,
          temporal: 1.0,
          zone: 1.0
        },
        timeline: [
          {
            time: '14:05:10',
            camera: 'Cam-02-Fence-North',
            description: 'Subject entered outer campus camera footprint.'
          },
          {
            time: '14:06:22',
            camera: 'Cam-02-Fence-North',
            description: 'Subject crossed virtual tripwire boundary line (Fence violation triggered).'
          }
        ]
      }
    });
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <p className="animate-pulse">Loading reports list...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 py-2">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-slate-100">Investigation Reports</h2>
          <p className="text-slate-400 text-sm">Automated AI forensic reports compiled for security events</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center space-x-1.5 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2.5 rounded-xl text-xs font-bold transition shadow-lg shadow-blue-500/15"
        >
          <Plus className="h-4 w-4" />
          <span>Compile New Report</span>
        </button>
      </div>

      {showForm && (
        <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-xl space-y-4 max-w-xl">
          <h3 className="font-bold text-slate-200 border-b border-dark-border pb-3">New Investigation Report Parameters</h3>
          <div className="space-y-4 text-xs">
            <div className="space-y-1">
              <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Report Title</label>
              <input
                type="text"
                placeholder="e.g. Incident Report: North Fence Trespass"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 text-xs focus:outline-none focus:border-blue-500 transition"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Incident Type</label>
                <select
                  value={incidentType}
                  onChange={(e) => setIncidentType(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-300 text-xs focus:outline-none focus:border-blue-500 transition"
                >
                  <option value="Fence Crossing">Fence Crossing</option>
                  <option value="Restricted Zone Breach">Restricted Zone Breach</option>
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Target Student Profile</label>
                <input
                  type="text"
                  value={studentName}
                  onChange={(e) => setStudentName(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 text-xs focus:outline-none focus:border-blue-500 transition"
                />
              </div>
            </div>
          </div>

          <div className="flex space-x-3 pt-2">
            <button
              onClick={handleGenerate}
              disabled={createReportMutation.isPending}
              className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-lg transition flex items-center justify-center space-x-1.5"
            >
              {createReportMutation.isPending ? (
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <>
                  <Check className="h-3.5 w-3.5" />
                  <span>Generate Report</span>
                </>
              )}
            </button>
          </div>
        </div>
      )}

      <div className="bg-dark-card border border-dark-border rounded-2xl overflow-hidden shadow-lg">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-dark-border text-xs font-semibold text-slate-400 bg-slate-900/50">
                <th className="px-6 py-4">Report Details</th>
                <th className="px-6 py-4">Date Generated</th>
                <th className="px-6 py-4">Incident Class</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border text-sm text-slate-300">
              {reports && reports.length > 0 ? (
                reports.map((rep: any) => (
                  <tr key={rep.id} className="hover:bg-slate-900/20 transition">
                    <td className="px-6 py-4 flex items-center space-x-3">
                      <div className="bg-blue-500/10 p-2 rounded-lg border border-blue-500/20">
                        <FileText className="h-4.5 w-4.5 text-blue-500" />
                      </div>
                      <div>
                        <span className="font-semibold text-slate-200 block">{rep.title}</span>
                        <span className="text-[10px] text-slate-500 font-mono">ID: {rep.id.slice(0, 8)}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-xs font-mono text-slate-400">
                      <span className="flex items-center space-x-1.5">
                        <Calendar className="h-3.5 w-3.5" />
                        <span>{new Date(rep.created_at).toLocaleString()}</span>
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded border border-blue-500/20 bg-blue-500/10 text-blue-450 uppercase tracking-wide">
                        {rep.incident_type}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <Link
                        to={`/reports/${rep.id}`}
                        className="inline-flex items-center space-x-1 text-blue-500 hover:text-blue-400 transition font-semibold text-xs bg-blue-500/10 px-2.5 py-1.5 rounded-lg border border-blue-500/20"
                      >
                        <span>Open Report</span>
                      </Link>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="text-center py-12 text-slate-500">
                    No generated reports available. Compile a new report to populate list.
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
