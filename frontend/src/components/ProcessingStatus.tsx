import React from 'react';
import { Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';

interface ProcessingStatusProps {
  status: string;
  stage?: string;
  progress: number;
  error?: string;
}

export const ProcessingStatus: React.FC<ProcessingStatusProps> = ({
  status,
  stage = "Pending Queue",
  progress,
  error
}) => {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Pipeline Stage</span>
          <h4 className="font-semibold text-slate-900 capitalize">{stage}</h4>
        </div>
        <div>
          {status === 'completed' && <CheckCircle2 className="h-6 w-6 text-emerald-600" />}
          {status === 'failed' && <AlertTriangle className="h-6 w-6 text-red-600" />}
          {status !== 'completed' && status !== 'failed' && (
            <Loader2 className="h-6 w-6 text-blue-600 animate-spin" />
          )}
        </div>
      </div>
      
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs font-semibold">
          <span className="text-slate-600 capitalize">Status: {status}</span>
          <span className="text-blue-600">{progress}%</span>
        </div>
        <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden border border-slate-200">
          <div
            className={`h-full transition-all duration-500 ${
              status === 'failed' 
                ? 'bg-red-500' 
                : status === 'completed' 
                  ? 'bg-emerald-500' 
                  : 'bg-blue-600'
            }`}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg p-3">
          {error}
        </div>
      )}
    </div>
  );
};
