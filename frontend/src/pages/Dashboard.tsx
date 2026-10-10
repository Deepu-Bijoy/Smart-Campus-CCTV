import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { Video, Film, Eye, Users, ArrowRight, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';

export const Dashboard: React.FC = () => {
  const { data: metrics, isLoading, isError, refetch } = useQuery({
    queryKey: ['dashboard-metrics'],
    queryFn: async () => {
      const response = await api.get('/dashboard');
      return response.data;
    },
    staleTime: 15000,
  });

  const { data: recentVideos, isLoading: videosLoading } = useQuery({
    queryKey: ['recent-videos'],
    queryFn: async () => {
      try {
        const response = await api.get('/videos?limit=5');
        if (Array.isArray(response.data)) {
          return response.data;
        }
        if (response.data && Array.isArray(response.data.items)) {
          return response.data.items;
        }
        return [];
      } catch (err) {
        console.error('Failed to fetch recent videos for dashboard:', err);
        return [];
      }
    },
    staleTime: 15000,
  });

  const cards = [
    { title: 'Surveillance Feeds', count: metrics?.total_videos ?? 0, icon: Film, color: 'text-blue-600 bg-blue-50 border-blue-100' },
    { title: 'Trajectories (Tracks)', count: metrics?.total_tracks ?? 0, icon: Video, color: 'text-emerald-600 bg-emerald-50 border-emerald-100' },
    { title: 'Coordinate Detections', count: metrics?.total_detections ?? 0, icon: Eye, color: 'text-purple-600 bg-purple-50 border-purple-100' },
    { title: 'Enrolled Profiles', count: metrics?.enrolled_students ?? 0, icon: Users, color: 'text-pink-600 bg-pink-50 border-pink-100' },
  ];

  if (isLoading && !metrics) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 h-96">
        <div className="text-center space-y-2">
          <p className="animate-pulse font-medium">Loading system statistics...</p>
        </div>
      </div>
    );
  }

  if (isError && !metrics) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-slate-600 h-96 space-y-4">
        <p className="text-rose-600 font-medium">Failed to load system statistics</p>
        <button
          onClick={() => refetch()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold transition shadow-sm"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-8 py-2">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Surveillance Headquarters</h2>
          <p className="text-slate-500 text-sm">Aggregated logs and tracking diagnostics</p>
        </div>
        <Link
          to="/upload"
          className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-xl font-semibold transition text-sm shadow-sm"
        >
          <span>Ingest New Feed</span>
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {cards.map((card) => (
          <div key={card.title} className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm flex items-center space-x-5">
            <div className={`p-4 rounded-xl border ${card.color}`}>
              <card.icon className="h-6 w-6" />
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{card.title}</p>
              <h3 className="text-2xl font-bold text-slate-900 mt-1">{card.count}</h3>
            </div>
          </div>
        ))}
      </div>

      {/* Main Grid split */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
            <h3 className="font-bold text-slate-900 text-lg mb-6">Recent Video Ingestions</h3>
            <div className="divide-y divide-slate-100">
              {videosLoading ? (
                <div className="text-center py-8 text-slate-400 text-sm animate-pulse">
                  Loading recent surveillance feeds...
                </div>
              ) : recentVideos && recentVideos.length > 0 ? (
                recentVideos.map((vid: any) => (
                  <div key={vid.id} className="py-4 flex items-center justify-between first:pt-0 last:pb-0">
                    <div>
                      <h4 className="font-semibold text-slate-900 text-sm">{vid.filename}</h4>
                      <p className="text-xs text-slate-500 mt-1 font-mono">{(vid.file_size / (1024 * 1024)).toFixed(1)} MB • {new Date(vid.created_at).toLocaleDateString()}</p>
                    </div>
                    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
                      vid.status === 'completed' 
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200' 
                        : vid.status === 'failed'
                          ? 'bg-red-50 text-red-700 border-red-200'
                          : 'bg-blue-50 text-blue-700 border-blue-200'
                    }`}>
                      {vid.status}
                    </span>
                  </div>
                ))
              ) : (
                <div className="text-center py-8 text-slate-400 text-sm">
                  No video assets currently ingested.
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-4">
            <div className="flex items-center space-x-2 text-blue-600">
              <ShieldCheck className="h-5 w-5" />
              <h3 className="font-bold text-slate-900">Investigation Center</h3>
            </div>
            <p className="text-sm text-slate-600">
              Use visual identification models to search appearance timelines, run AI-powered query lookups, and index student directories.
            </p>
            <div className="space-y-2 pt-2">
              <Link to="/search" className="block text-center py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-semibold transition shadow-sm">
                Search CCTV footage
              </Link>
              <Link to="/students" className="block text-center py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-sm font-medium transition">
                Manage Student Profiles
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
