import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { Film, Trash2, Eye, Activity } from 'lucide-react';
import { Link } from 'react-router-dom';
import { DeleteConfirmationModal } from '../components/DeleteConfirmationModal';

export const Videos: React.FC = () => {
  const queryClient = useQueryClient();
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [selectedVideoStatus, setSelectedVideoStatus] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/videos/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['videos-list'] });
      setIsDeleteModalOpen(false);
      setSelectedVideoId(null);
      setSelectedVideoStatus(null);
    },
    onError: (err: any) => {
      alert(`Deletion failed: ${err.response?.data?.detail || err.message}`);
      setIsDeleteModalOpen(false);
      setSelectedVideoId(null);
      setSelectedVideoStatus(null);
    }
  });

  const { data: videos, isLoading } = useQuery({
    queryKey: ['videos-list'],
    queryFn: async () => {
      const response = await api.get('/videos');
      return Array.isArray(response.data) ? response.data : (response.data.items || []);
    }
  });

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        Loading video feeds...
      </div>
    );
  }

  return (
    <div className="space-y-8 py-2">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Surveillance Feeds</h2>
        <p className="text-slate-400 text-sm">Upload logs, parsing state stages, and tracking indices</p>
      </div>

      <div className="bg-dark-card border border-dark-border rounded-2xl overflow-hidden shadow-lg">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-dark-border text-xs font-semibold text-slate-400 bg-slate-900/50">
                <th className="px-6 py-4">Filename</th>
                <th className="px-6 py-4">Resolution / Stage</th>
                <th className="px-6 py-4">Status</th>
                <th className="px-6 py-4">Date Uploaded</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border text-sm text-slate-300">
              {videos && videos.length > 0 ? (
                videos.map((vid: any) => (
                  <tr key={vid.id} className="hover:bg-slate-900/20 transition">
                    <td className="px-6 py-4 flex items-center space-x-3">
                      <Film className="h-5 w-5 text-blue-500 flex-shrink-0" />
                      <div>
                        <span className="font-semibold text-slate-200 block max-w-xs truncate">{vid.filename}</span>
                        <span className="text-xs text-slate-500 font-mono">{(vid.file_size / (1024 * 1024)).toFixed(1)} MB</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      {vid.status === 'processing' ? (
                        <div className="flex items-center space-x-2">
                          <Activity className="h-4 w-4 text-blue-400 animate-pulse" />
                          <span className="text-xs text-blue-400">{vid.current_stage || 'Queueing'} ({vid.progress_percentage}%)</span>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-400">{vid.width ? `${vid.width}x${vid.height} @ ${vid.fps} FPS` : 'N/A'}</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
                        vid.status === 'completed' 
                          ? 'bg-green-500/10 text-green-500 border-green-500/20' 
                          : vid.status === 'failed'
                            ? 'bg-red-500/10 text-red-500 border-red-500/20'
                            : 'bg-blue-500/10 text-blue-500 border-blue-500/20'
                      }`}>
                        {vid.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-xs font-mono text-slate-400">
                      {new Date(vid.created_at).toLocaleString()}
                    </td>
                    <td className="px-6 py-4 text-right space-x-3">
                      {vid.status === 'completed' && (
                        <Link
                          to={`/timeline/${vid.id}`}
                          className="inline-flex items-center space-x-1.5 text-blue-500 hover:text-blue-400 transition font-semibold text-xs bg-blue-500/10 px-2.5 py-1.5 rounded-lg border border-blue-500/20"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          <span>View Tracks</span>
                        </Link>
                      )}
                      <button
                        onClick={() => {
                          if (vid.status === 'processing') {
                            alert('Cannot delete a video feed while it is actively processing.');
                            return;
                          }
                          setSelectedVideoId(vid.id);
                          setSelectedVideoStatus(vid.status);
                          setIsDeleteModalOpen(true);
                        }}
                        disabled={deleteMutation.isPending}
                        className="text-slate-400 hover:text-red-500 transition p-1.5 hover:bg-red-500/10 rounded-lg border border-transparent hover:border-red-500/20 inline-block disabled:opacity-50"
                        title="Delete Video"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="text-center py-12 text-slate-500">
                    No surveillance videos currently uploaded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <DeleteConfirmationModal
        isOpen={isDeleteModalOpen}
        onClose={() => { setIsDeleteModalOpen(false); setSelectedVideoId(null); setSelectedVideoStatus(null); }}
        onConfirm={() => { if (selectedVideoId) deleteMutation.mutate(selectedVideoId); }}
        title="Delete CCTV Video Feed"
        message="Deleting this video will remove associated AI analysis data, events, and tracking indices. Continue?"
        isLoading={deleteMutation.isPending}
      />
    </div>
  );
};
