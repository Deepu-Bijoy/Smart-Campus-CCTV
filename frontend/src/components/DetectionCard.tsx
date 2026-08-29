import React from 'react';
import { Eye } from 'lucide-react';

interface DetectionCardProps {
  cropPath: string;
  camera: string;
  timestamp: number;
  objectClass: string;
  score?: number;
  onClick?: () => void;
}

export const DetectionCard: React.FC<DetectionCardProps> = ({
  cropPath,
  camera,
  timestamp,
  objectClass,
  score,
  onClick
}) => {
  const imageUrl = cropPath.startsWith('http') ? cropPath : `http://127.0.0.1:8000/${cropPath.replace(/^\/+/, '')}`;

  return (
    <div
      onClick={onClick}
      className="bg-dark-card border border-dark-border rounded-xl overflow-hidden hover:border-blue-500/50 transition cursor-pointer shadow-md"
    >
      <div className="aspect-square bg-slate-950 flex items-center justify-center relative overflow-hidden group">
        <img
          src={imageUrl}
          alt={objectClass}
          className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
          onError={(e) => {
            (e.target as HTMLImageElement).src = 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150';
          }}
        />
        {score && (
          <div className="absolute top-2 right-2 bg-blue-600 text-white font-mono text-xs px-2 py-0.5 rounded border border-blue-500/30">
            {(score * 100).toFixed(0)}% Match
          </div>
        )}
      </div>
      <div className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-blue-500 uppercase tracking-wider">{objectClass}</span>
          <span className="text-xs text-slate-400 font-mono">{timestamp.toFixed(1)}s</span>
        </div>
        <div className="flex items-center text-xs text-slate-400 space-x-1">
          <Eye className="h-3.5 w-3.5 text-slate-500" />
          <span>{camera}</span>
        </div>
      </div>
    </div>
  );
};
