import React from 'react';
import { Calendar, Eye, FileText, Landmark } from 'lucide-react';

export interface TimelineItemData {
  id: string;
  event_type: string;
  timestamp: string;
  label: string;
  description: string;
  metadata: Record<string, any>;
}

interface TimelineProps {
  items: TimelineItemData[];
}

export const Timeline: React.FC<TimelineProps> = ({ items }) => {
  if (!items || items.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500">
        No timeline events found.
      </div>
    );
  }

  const getIcon = (type: string) => {
    switch (type) {
      case 'enrollment':
        return <Landmark className="h-5 w-5 text-blue-500" />;
      case 'detection':
        return <Eye className="h-5 w-5 text-green-500" />;
      default:
        return <FileText className="h-5 w-5 text-slate-500" />;
    }
  };

  return (
    <div className="relative border-l border-slate-200 ml-4 pl-8 space-y-8 py-4">
      {items.map((item) => (
        <div key={item.id} className="relative">
          <span className="absolute -left-[45px] top-1 bg-white border border-slate-200 rounded-full p-2 shadow-sm">
            {getIcon(item.event_type)}
          </span>
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-slate-900">{item.label}</h3>
              <span className="flex items-center text-xs text-slate-500 space-x-1">
                <Calendar className="h-3 w-3" />
                <span>{new Date(item.timestamp).toLocaleString()}</span>
              </span>
            </div>
            <p className="text-sm text-slate-600 mb-3">{item.description}</p>
            {item.metadata && Object.keys(item.metadata).length > 0 && (
              <div className="bg-slate-50 rounded-lg p-3 text-xs space-y-1 border border-slate-200">
                {Object.entries(item.metadata).map(([key, val]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-slate-500 font-medium capitalize">{key.replace('_', ' ')}</span>
                    <span className="text-slate-800 font-mono">{typeof val === 'object' ? JSON.stringify(val) : String(val)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};
