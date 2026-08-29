import React, { useState, useRef } from 'react';
import { Check, RefreshCw, X } from 'lucide-react';

interface Point {
  x: number;
  y: number;
}

interface VirtualZoneEditorProps {
  onSave: (zone: { name: string; zoneType: string; geometryType: string; coordinates: string }) => void;
  onCancel?: () => void;
}

export const VirtualZoneEditor: React.FC<VirtualZoneEditorProps> = ({ onSave, onCancel }) => {
  const [points, setPoints] = useState<Point[]>([]);
  const [name, setName] = useState('');
  const [zoneType, setZoneType] = useState('Restricted Area');
  const [geometryType, setGeometryType] = useState('polygon');
  const svgRef = useRef<SVGSVGElement | null>(null);

  const handleSvgClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const scaleX = 640 / rect.width;
    const scaleY = 360 / rect.height;
    
    const x = Math.round((e.clientX - rect.left) * scaleX);
    const y = Math.round((e.clientY - rect.top) * scaleY);
    
    if (geometryType === 'line' && points.length >= 2) {
      setPoints([{ x, y }]);
    } else {
      setPoints([...points, { x, y }]);
    }
  };

  const handleReset = () => {
    setPoints([]);
  };

  const handleSave = () => {
    if (points.length < 2) {
      alert('Draw at least 2 points for a line, or 3 points for a polygon.');
      return;
    }
    if (!name) {
      alert('Provide a label/name for this virtual zone.');
      return;
    }
    const coordsStr = JSON.stringify(points.map(p => [p.x, p.y]));
    onSave({
      name,
      zoneType,
      geometryType,
      coordinates: coordsStr
    });
    setPoints([]);
    setName('');
  };

  return (
    <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-xl space-y-6">
      <div className="flex items-center justify-between border-b border-dark-border/50 pb-3">
        <h3 className="font-bold text-slate-200">Draw Virtual Zone Boundary</h3>
        <button onClick={handleReset} className="flex items-center space-x-1.5 text-xs text-slate-400 hover:text-slate-200 transition">
          <RefreshCw className="h-3.5 w-3.5" />
          <span>Clear Canvas</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* SVG Canvas */}
        <div className="md:col-span-2 relative aspect-[16/9] bg-slate-950 rounded-xl border border-dark-border overflow-hidden select-none">
          <div className="absolute inset-0 bg-slate-900/50 flex items-center justify-center pointer-events-none">
            <span className="text-slate-600 text-xs font-mono font-bold uppercase tracking-wider">Surveillance Snapshot</span>
          </div>

          <svg
            ref={svgRef}
            onClick={handleSvgClick}
            viewBox="0 0 640 360"
            className="absolute inset-0 w-full h-full cursor-crosshair z-10"
          >
            {geometryType === 'polygon' && points.length > 1 && (
              <polygon
                points={points.map(p => `${p.x},${p.y}`).join(' ')}
                className="fill-blue-500/20 stroke-blue-500 stroke-2"
              />
            )}

            {geometryType === 'line' && points.length > 1 && (
              <line
                x1={points[0].x}
                y1={points[0].y}
                x2={points[1].x}
                y2={points[1].y}
                className="stroke-blue-500 stroke-2"
              />
            )}

            {points.map((p, idx) => (
              <circle
                key={idx}
                cx={p.x}
                cy={p.y}
                r="5"
                className="fill-red-500 stroke-white stroke-2"
              />
            ))}
          </svg>
        </div>

        {/* Inputs */}
        <div className="space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <div className="space-y-1">
              <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Zone Name</label>
              <input
                type="text"
                placeholder="e.g. Fence Boundary West"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500 transition"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Boundary Geometry</label>
              <select
                value={geometryType}
                onChange={(e) => { setGeometryType(e.target.value); setPoints([]); }}
                className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-300 text-sm focus:outline-none focus:border-blue-500 transition capitalize"
              >
                <option value="polygon">polygon (Area)</option>
                <option value="line">line (Tripwire)</option>
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Classification</label>
              <select
                value={zoneType}
                onChange={(e) => setZoneType(e.target.value)}
                className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-300 text-sm focus:outline-none focus:border-blue-500 transition capitalize"
              >
                {['Fence', 'Restricted Area', 'Gate', 'Road', 'Parking'].map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex space-x-3 pt-4">
            {onCancel && (
              <button
                type="button"
                onClick={onCancel}
                className="flex-1 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl text-sm font-semibold transition flex items-center justify-center space-x-1"
              >
                <X className="h-4 w-4" />
                <span>Cancel</span>
              </button>
            )}
            <button
              type="button"
              onClick={handleSave}
              className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-semibold shadow-lg shadow-blue-500/15 transition flex items-center justify-center space-x-1"
            >
              <Check className="h-4 w-4" />
              <span>Apply Zone</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
