import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { UploadCloud, FileSpreadsheet, RefreshCw, AlertTriangle, Play, Ban } from 'lucide-react';

export const BulkImport: React.FC = () => {
  const queryClient = useQueryClient();
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [importReport, setImportReport] = useState<any | null>(null);

  // Poll active import status
  const { data: jobStatus } = useQuery({
    queryKey: ['import-job-status', activeJobId],
    queryFn: async () => {
      if (!activeJobId) return null;
      const res = await api.get(`/students/import/status/${activeJobId}`);
      return res.data;
    },
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const data = query.state.data as any;
      if (data && (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled')) {
        return false;
      }
      return 2000; // poll every 2s
    }
  });

  const uploadCsvMutation = useMutation({
    mutationFn: async () => {
      if (!csvFile) return;
      const formData = new FormData();
      formData.append('file', csvFile);
      const res = await api.post('/students/import', formData);
      return res.data;
    },
    onSuccess: (data) => {
      alert('Spreadsheet import completed successfully!');
      setCsvFile(null);
      if (data && data.id) {
        setActiveJobId(data.id);
      }
    },
    onError: (err: any) => {
      alert(`Import failed: ${err.response?.data?.detail || err.message}`);
    }
  });

  const uploadZipMutation = useMutation({
    mutationFn: async () => {
      if (!zipFile) return;
      const formData = new FormData();
      formData.append('file', zipFile);
      const res = await api.post('/students/import/photos', formData);
      return res.data;
    },
    onSuccess: (data) => {
      alert(`ZIP Photos dataset uploaded successfully! Matched: ${data.matched_photos_count} photos.`);
      setZipFile(null);
    },
    onError: (err: any) => {
      alert(`Upload failed: ${err.response?.data?.detail || err.message}`);
    }
  });

  const triggerEnrollmentMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/students/import/enroll');
      return res.data;
    },
    onSuccess: (data) => {
      if (data && data.id) {
        setActiveJobId(data.id);
      }
    }
  });

  const cancelJobMutation = useMutation({
    mutationFn: async () => {
      if (!activeJobId) return;
      const res = await api.put(`/students/import/cancel/${activeJobId}`);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['import-job-status', activeJobId] });
    }
  });

  // Fetch report logs when job finishes
  useEffect(() => {
    if (jobStatus && (jobStatus.status === 'completed' || jobStatus.status === 'failed')) {
      api.get(`/students/import/report/${activeJobId}`).then((res) => {
        setImportReport(res.data);
      });
    }
  }, [jobStatus, activeJobId]);

  return (
    <div className="space-y-8 py-2">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Bulk Student Import</h2>
        <p className="text-slate-400 text-sm">Automate campus face enrollment database registrations in batches</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Upload forms */}
        <div className="space-y-6">
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <h3 className="font-bold text-slate-200 text-lg flex items-center space-x-2">
              <FileSpreadsheet className="h-5 w-5 text-blue-500" />
              <span>Import Student Spreadsheet</span>
            </h3>
            
            <div className="border-2 border-dashed border-dark-border rounded-xl p-6 text-center hover:bg-slate-900/10 transition relative">
              <input
                type="file"
                accept=".csv,.xlsx"
                onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
              <UploadCloud className="h-8 w-8 text-slate-500 mx-auto mb-2" />
              <span className="text-xs text-slate-300 block font-semibold">
                {csvFile ? csvFile.name : 'Select or drag student list (CSV/Excel)'}
              </span>
              <span className="text-[10px] text-slate-500 block mt-1">Maximum spreadsheet limit 5MB</span>
            </div>

            {csvFile && (
              <button
                onClick={() => uploadCsvMutation.mutate()}
                disabled={uploadCsvMutation.isPending}
                className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-500 text-white rounded-xl font-bold text-xs shadow-lg transition flex items-center justify-center space-x-1.5"
              >
                {uploadCsvMutation.isPending && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
                <span>Upload Spreadsheet</span>
              </button>
            )}
          </div>

          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <h3 className="font-bold text-slate-200 text-lg flex items-center space-x-2">
              <UploadCloud className="h-5 w-5 text-blue-500" />
              <span>Import Structured Face Dataset</span>
            </h3>

            <div className="border-2 border-dashed border-dark-border rounded-xl p-6 text-center hover:bg-slate-900/10 transition relative">
              <input
                type="file"
                accept=".zip"
                onChange={(e) => setZipFile(e.target.files?.[0] || null)}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
              <UploadCloud className="h-8 w-8 text-slate-500 mx-auto mb-2" />
              <span className="text-xs text-slate-300 block font-semibold">
                {zipFile ? zipFile.name : 'Select or drag structured ZIP dataset'}
              </span>
              <span className="text-[10px] text-slate-500 block mt-1">Dataset directories should match Roll Numbers</span>
            </div>

            {zipFile && (
              <button
                onClick={() => uploadZipMutation.mutate()}
                disabled={uploadZipMutation.isPending}
                className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-500 text-white rounded-xl font-bold text-xs shadow-lg transition flex items-center justify-center space-x-1.5"
              >
                {uploadZipMutation.isPending && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
                <span>Upload ZIP Archive</span>
              </button>
            )}
          </div>
        </div>

        {/* Status and Active Jobs panels */}
        <div className="space-y-6">
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-6">
            <div className="flex justify-between items-center">
              <h3 className="font-bold text-slate-200 text-lg">Active Enrollment Pipeline</h3>
              {!activeJobId && (
                <button
                  onClick={() => triggerEnrollmentMutation.mutate()}
                  className="flex items-center space-x-1.5 bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-lg text-xs font-bold transition"
                >
                  <Play className="h-3.5 w-3.5" />
                  <span>Start Enrollment</span>
                </button>
              )}
            </div>

            {jobStatus ? (
              <div className="space-y-5 text-sm">
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 text-xs uppercase font-semibold">Job ID</span>
                  <span className="font-mono text-xs text-slate-300">{jobStatus.id.slice(0, 8)}</span>
                </div>

                <div className="flex justify-between items-center">
                  <span className="text-slate-400 text-xs uppercase font-semibold">Status</span>
                  <span className={`text-xs font-bold px-2.5 py-0.5 rounded-full border ${
                    jobStatus.status === 'processing'
                      ? 'bg-blue-500/10 text-blue-450 border-blue-500/20'
                      : jobStatus.status === 'completed'
                      ? 'bg-green-500/10 text-green-500 border-green-500/20'
                      : 'bg-slate-800 text-slate-400 border-dark-border'
                  }`}>
                    {jobStatus.status}
                  </span>
                </div>

                {jobStatus.status === 'processing' && (
                  <div className="space-y-2">
                    <div className="flex justify-between text-xs text-slate-400">
                      <span>Currently compiling: {jobStatus.current_roll_number || 'N/A'}</span>
                      <span className="font-mono">
                        {jobStatus.processed_records} / {jobStatus.total_records}
                      </span>
                    </div>
                    <div className="w-full bg-slate-900 rounded-full h-2 overflow-hidden border border-dark-border">
                      <div
                        className="bg-blue-500 h-full rounded-full transition-all duration-300"
                        style={{ width: `${(jobStatus.processed_records / (jobStatus.total_records || 1)) * 100}%` }}
                      />
                    </div>
                    {jobStatus.estimated_remaining_seconds !== null && (
                      <span className="text-[10px] text-slate-500 block text-right font-mono">
                        Estimated remaining: {jobStatus.estimated_remaining_seconds.toFixed(0)} seconds
                      </span>
                    )}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4 text-center pt-2">
                  <div className="bg-slate-900/50 p-3 rounded-xl border border-dark-border/40">
                    <span className="text-green-500 text-lg font-bold block">{jobStatus.successful_records}</span>
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Success</span>
                  </div>
                  <div className="bg-slate-900/50 p-3 rounded-xl border border-dark-border/40">
                    <span className="text-red-500 text-lg font-bold block">{jobStatus.failed_records}</span>
                    <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Failed</span>
                  </div>
                </div>

                {jobStatus.status === 'processing' && (
                  <button
                    onClick={() => cancelJobMutation.mutate()}
                    className="w-full py-2 bg-red-950 border border-red-800/40 hover:bg-red-900 text-red-400 rounded-xl text-xs font-bold transition flex items-center justify-center space-x-1.5"
                  >
                    <Ban className="h-4 w-4" />
                    <span>Cancel active job</span>
                  </button>
                )}
              </div>
            ) : (
              <div className="text-center py-8 text-slate-500 text-xs italic">
                No active import or enrollment pipeline runs.
              </div>
            )}
          </div>

          {/* Import report failures */}
          {importReport && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <h3 className="font-bold text-slate-200 text-lg">Import Diagnostic Report</h3>
              <div className="divide-y divide-dark-border/50 max-h-60 overflow-y-auto">
                {importReport.errors && importReport.errors.length > 0 ? (
                  importReport.errors.map((err: any, idx: number) => (
                    <div key={idx} className="py-2.5 flex items-start space-x-2 text-xs">
                      <AlertTriangle className="h-4 w-4 text-yellow-500 mt-0.5" />
                      <div>
                        <span className="font-bold text-slate-350 block">Roll No: {err.roll_number || 'Unknown'}</span>
                        <span className="text-slate-500">{err.error}</span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-center py-6 text-slate-500 text-xs">
                    No errors detected in this batch run! All students verified.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
