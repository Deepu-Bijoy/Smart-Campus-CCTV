import React from 'react';
import { Sliders, CheckCircle2 } from 'lucide-react';

export const Settings: React.FC = () => {
  return (
    <div className="max-w-2xl mx-auto py-4 space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">System Parameters</h2>
        <p className="text-slate-400 text-sm">Tune detection confidence thresholds, similarity score parameters and hardware optimizations</p>
      </div>

      <div className="bg-dark-card border border-dark-border rounded-2xl p-8 shadow-xl space-y-6">
        <div className="flex items-center space-x-2 text-blue-500 border-b border-dark-border pb-4">
          <Sliders className="h-5 w-5" />
          <h3 className="font-bold text-slate-200 text-lg">Model Parameters</h3>
        </div>

        <div className="space-y-6">
          <div className="space-y-2">
            <div className="flex justify-between text-sm font-semibold">
              <span className="text-slate-300">YOLO Person Confidence Gate</span>
              <span className="text-blue-500">0.50</span>
            </div>
            <input
              type="range"
              min="0.10"
              max="0.95"
              step="0.05"
              defaultValue="0.50"
              className="w-full h-1 bg-slate-900 rounded-lg appearance-none cursor-pointer accent-blue-600"
            />
            <p className="text-xs text-slate-500">Sets the strictness for detecting humans in surveillance video frames.</p>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-sm font-semibold">
              <span className="text-slate-300">ArcFace Match High Threshold</span>
              <span className="text-blue-500">0.75</span>
            </div>
            <input
              type="range"
              min="0.50"
              max="0.95"
              step="0.05"
              defaultValue="0.75"
              className="w-full h-1 bg-slate-900 rounded-lg appearance-none cursor-pointer accent-blue-600"
            />
            <p className="text-xs text-slate-500">Threshold required to register a recognition event with High Confidence.</p>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-sm font-semibold">
              <span className="text-slate-300">ArcFace Match Medium Threshold</span>
              <span className="text-blue-500">0.60</span>
            </div>
            <input
              type="range"
              min="0.40"
              max="0.80"
              step="0.05"
              defaultValue="0.60"
              className="w-full h-1 bg-slate-900 rounded-lg appearance-none cursor-pointer accent-blue-600"
            />
            <p className="text-xs text-slate-500">Threshold required to register a recognition event with Medium Confidence.</p>
          </div>
        </div>

        <div className="bg-slate-900/50 rounded-xl p-4 border border-dark-border flex items-start space-x-3">
          <CheckCircle2 className="h-5 w-5 text-green-500 flex-shrink-0 mt-0.5" />
          <div className="text-xs space-y-1">
            <span className="font-semibold text-slate-200 block">Autosave Enabled</span>
            <p className="text-slate-400">Settings changes are mapped automatically to the active running worker process configs.</p>
          </div>
        </div>
      </div>
    </div>
  );
};
