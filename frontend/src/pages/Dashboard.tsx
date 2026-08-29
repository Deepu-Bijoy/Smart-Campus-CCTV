import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { Video, Film, Eye, Users, ArrowRight, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';

export const Dashboard: React.FC = () => {
  const { data: metrics, isLoading } = useQuery({
    queryKey: ['dashboard-metrics'],
    queryFn: async () => {
      const response = await api.get('/dashboard');
      return response.data;
    }
  });

  const { data: recentVideos } = useQuery({
    queryKey: ['recent-videos'],
    queryFn: async () => {
      const response = await api.get('/videos?limit=5');
      return response.data.items || [];
    }
  });

  const cards = [
    { title: 'Surveillance Feeds', count: metrics?.total_videos ?? 0, icon: Film, color: 'text-blue-500 bg-blue-500/10 border-blue-500/20' },
    { title: 'Trajectories (Tracks)', count: metrics?.total_tracks ?? 0, icon: Video, color: 'text-green-500 bg-green-500/10 border-green-500/20' },
    { title: 'Coordinate Detections', count: metrics?.total_detections ?? 0, icon: Eye, color: 'text-purple-500 bg-purple-500/10 border-purple-500/20' },
    { title: 'Enrolled Profiles', count: metrics?.enrolled_students ?? 0, icon: Users, color: 'text-pink-500 bg-pink-500/10 border-pink-500/20' },
  ];

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <div className="text-center space-y-2">
          <p className="animate-pulse">Loading system statistics...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 py-2">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-100">Surveillance Headquarters</h2>
          <p className="text-slate-400 text-sm">Aggregated logs and tracking diagnostics</p>
        </div>
        <Link
          to="/upload"
          className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-500 text-white px-5 py-2.5 rounded-xl font-semibold transition text-sm shadow-lg shadow-blue-500/15"
        >
          <span>Ingest New Feed</span>
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {cards.map((card) => (
          <div key={card.title} className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md flex items-center space-x-5">
            <div className={`p-4 rounded-xl border ${card.color}`}>
              <card.icon className="h-6 w-6" />
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{card.title}</p>
              <h3 className="text-2xl font-bold text-slate-100 mt-1">{card.count}</h3>
            </div>
          </div>
        ))}
      </div>

      {/* Main Grid split */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md">
            <h3 className="font-bold text-slate-200 text-lg mb-6">Recent Video Ingestions</h3>
            <div className="divide-y divide-dark-border">
              {recentVideos && recentVideos.length > 0 ? (
                recentVideos.map((vid: any) => (
                  <div key={vid.id} className="py-4 flex items-center justify-between first:pt-0 last:pb-0">
                    <div>
                      <h4 className="font-semibold text-slate-300 text-sm">{vid.filename}</h4>
                      <p className="text-xs text-slate-500 mt-1 font-mono">{(vid.file_size / (1024 * 1024)).toFixed(1)} MB • {new Date(vid.created_at).toLocaleDateString()}</p>
                    </div>
                    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
                      vid.status === 'completed' 
                        ? 'bg-green-500/10 text-green-500 border-green-500/20' 
                        : vid.status === 'failed'
                          ? 'bg-red-500/10 text-red-500 border-red-500/20'
                          : 'bg-blue-500/10 text-blue-500 border-blue-500/20'
                    }`}>
                      {vid.status}
                    </span>
                  </div>
                ))
              ) : (
                <div className="text-center py-8 text-slate-500 text-sm">
                  No video assets currently ingested.
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <div className="flex items-center space-x-2 text-blue-500">
              <ShieldCheck className="h-5 w-5" />
              <h3 className="font-bold text-slate-200">Investigation Center</h3>
            </div>
            <p className="text-sm text-slate-400">
              Use visual identification models to search appearance timelines, run AI-powered query lookups, and index student directories.
            </p>
            <div className="space-y-2 pt-2">
              <Link to="/search" className="block text-center py-2.5 bg-blue-600/10 hover:bg-blue-600/20 text-blue-400 rounded-xl text-sm font-semibold border border-blue-500/20 transition">
                Search CCTV footage
              </Link>
              <Link to="/students" className="block text-center py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white rounded-xl text-sm font-medium transition">
                Manage Student Profiles
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
