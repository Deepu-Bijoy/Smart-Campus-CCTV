import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { Film, Trash2, Activity, Clock, AlertCircle } from 'lucide-react';
import { DeleteConfirmationModal } from '../components/DeleteConfirmationModal';

const TERMINAL_STATUSES = ['completed', 'failed', 'cancelled'];

export const Videos: React.FC = () => {
  const queryClient = useQueryClient();
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      setDeleteError(null);
      await api.delete(`/videos/${id}`);
      return id;
    },
    retry: false,
    onMutate: async (id: string) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ['videos-list'] }),
        queryClient.cancelQueries({ queryKey: ['recent-videos'] }),
      ]);
      const previousVideos = queryClient.getQueryData(['videos-list']);
      const previousRecent = queryClient.getQueryData(['recent-videos']);

      queryClient.setQueryData(['videos-list'], (old: any) => {
        if (!old) return old;
        if (Array.isArray(old)) {
          return old.filter((v: any) => v.id !== id);
        }
        if (old.items && Array.isArray(old.items)) {
          return {
            ...old,
            total: Math.max(0, (old.total || 1) - 1),
            items: old.items.filter((v: any) => v.id !== id),
          };
        }
        return old;
      });

      queryClient.setQueryData(['recent-videos'], (old: any) => {
        if (!old) return old;
        if (Array.isArray(old)) {
          return old.filter((v: any) => v.id !== id);
        }
        if (old.items && Array.isArray(old.items)) {
          return {
            ...old,
            items: old.items.filter((v: any) => v.id !== id),
          };
        }
        return old;
      });

      return { previousVideos, previousRecent };
    },
    onSuccess: async () => {
      setIsDeleteModalOpen(false);
      setSelectedVideoId(null);
      setDeleteError(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['videos-list'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] }),
        queryClient.invalidateQueries({ queryKey: ['recent-videos'] }),
      ]);
    },
    onError: (err: any, _id: string, context: any) => {
      if (context?.previousVideos) {
        queryClient.setQueryData(['videos-list'], context.previousVideos);
      }
      if (context?.previousRecent) {
        queryClient.setQueryData(['recent-videos'], context.previousRecent);
      }
      const msg = err.response?.data?.detail || "Unable to delete this video because related analysis records could not be removed. No changes were committed.";
      setDeleteError(msg);
      setIsDeleteModalOpen(false);
      setSelectedVideoId(null);
    }
  });

  const { data: videos, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['videos-list'],
    queryFn: async () => {
      const response = await api.get('/videos');
      return Array.isArray(response.data) ? response.data : (response.data.items || []);
    },
    staleTime: 5000,
    refetchInterval: (query) => {
      if (deleteMutation.isPending) return false;
      const data = query.state.data;
      const items = Array.isArray(data) ? data : (data?.items || []);
      const hasActive = items.some((v: any) => !TERMINAL_STATUSES.includes((v.status || '').toLowerCase()));
      return hasActive ? 2000 : false;
    },
    refetchIntervalInBackground: false,
  });

  const renderStatusBadge = (status: string) => {
    const s = (status || '').toLowerCase();
    switch (s) {
      case 'completed':
        return (
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200">
            completed
          </span>
        );
      case 'processing':
        return (
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full border bg-blue-50 text-blue-700 border-blue-200 inline-flex items-center space-x-1.5">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-600"></span>
            </span>
            <span>processing</span>
          </span>
        );
      case 'queued':
        return (
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full border bg-amber-50 text-amber-700 border-amber-200">
            queued
          </span>
        );
      case 'failed':
        return (
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full border bg-rose-50 text-rose-700 border-rose-200">
            failed
          </span>
        );
      case 'cancelled':
        return (
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full border bg-slate-100 text-slate-600 border-slate-200">
            cancelled
          </span>
        );
      default:
        return (
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full border bg-slate-50 text-slate-700 border-slate-200">
            {status}
          </span>
        );
    }
  };

  const renderResolutionOrStage = (vid: any) => {
    const status = (vid.status || '').toLowerCase();

    if (status === 'processing') {
      const pct = Math.min(100, Math.max(0, vid.progress_percentage || 0));
      return (
        <div className="space-y-1 max-w-xs">
          <div className="flex items-center space-x-1.5">
            <Activity className="h-3.5 w-3.5 text-blue-600 animate-pulse flex-shrink-0" />
            <span className="text-xs text-blue-700 font-medium truncate">
              {vid.current_stage || 'Processing'} — {pct}%
            </span>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden border border-slate-200/80">
            <div
              className="bg-blue-600 h-1.5 rounded-full transition-all duration-500 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      );
    }

    if (status === 'queued') {
      return (
        <div className="space-y-1 max-w-xs">
          <div className="flex items-center space-x-1.5">
            <Clock className="h-3.5 w-3.5 text-amber-500 animate-pulse flex-shrink-0" />
            <span className="text-xs text-amber-700 font-medium truncate">
              {vid.current_stage || 'Queued in pipeline'} (0%)
            </span>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden border border-slate-200/80">
            <div className="bg-amber-400 h-1.5 rounded-full w-0 transition-all duration-500" />
          </div>
        </div>
      );
    }

    if (status === 'failed') {
      return (
        <div className="space-y-0.5 max-w-xs">
          <div className="flex items-center space-x-1.5 text-rose-600">
            <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
            <span className="text-xs font-medium truncate">
              {vid.current_stage || 'Processing Failed'}
              {vid.progress_percentage > 0 ? ` (${vid.progress_percentage}%)` : ''}
            </span>
          </div>
          {vid.error_message && (
            <span className="text-[11px] text-rose-500 truncate block" title={vid.error_message}>
              {vid.error_message}
            </span>
          )}
        </div>
      );
    }

    if (status === 'cancelled') {
      return <span className="text-xs text-slate-500">Processing Cancelled</span>;
    }

    return (
      <span className="text-xs text-slate-500">
        {vid.width ? `${vid.width}x${vid.height} @ ${vid.fps ? Math.round(vid.fps) : 25} FPS` : 'N/A'}
      </span>
    );
  };

  if (isLoading && !videos) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        Loading video feeds...
      </div>
    );
  }

  if (isError && !videos) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-slate-600 h-96 space-y-4">
        <p className="text-rose-600 font-medium">Failed to load video feeds</p>
        <p className="text-xs text-slate-400 max-w-md text-center">
          {(error as any)?.response?.data?.detail || (error as any)?.message || 'An unexpected network error occurred.'}
        </p>
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
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Surveillance Feeds</h2>
        <p className="text-slate-500 text-sm">Upload logs, parsing state stages, and tracking indices</p>
      </div>

      {deleteError && (
        <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-sm flex items-center justify-between shadow-xs">
          <div className="flex items-center space-x-2">
            <span className="font-medium">{deleteError}</span>
          </div>
          <button
            onClick={() => setDeleteError(null)}
            className="text-rose-600 hover:text-rose-800 text-xs font-semibold px-2 py-1 rounded-md hover:bg-rose-100 transition"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-200 text-xs font-semibold text-slate-500 bg-slate-50">
                <th className="px-6 py-4">Filename</th>
                <th className="px-6 py-4">Resolution / Stage</th>
                <th className="px-6 py-4">Status</th>
                <th className="px-6 py-4">Date Uploaded</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm text-slate-700">
              {videos && videos.length > 0 ? (
                videos.map((vid: any) => (
                  <tr key={vid.id} className="hover:bg-slate-50 transition">
                    <td className="px-6 py-4 flex items-center space-x-3">
                      <Film className="h-5 w-5 text-blue-600 flex-shrink-0" />
                      <div>
                        <span className="font-semibold text-slate-900 block max-w-xs truncate">{vid.filename}</span>
                        <span className="text-xs text-slate-500 font-mono">{(vid.file_size / (1024 * 1024)).toFixed(1)} MB</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      {renderResolutionOrStage(vid)}
                    </td>
                    <td className="px-6 py-4">
                      {renderStatusBadge(vid.status)}
                    </td>
                    <td className="px-6 py-4 text-xs font-mono text-slate-500">
                      {new Date(vid.created_at).toLocaleString()}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button
                        onClick={() => {
                          setSelectedVideoId(vid.id);
                          setIsDeleteModalOpen(true);
                        }}
                        disabled={deleteMutation.isPending}
                        className="text-slate-400 hover:text-red-600 transition p-1.5 hover:bg-red-50 rounded-lg border border-transparent hover:border-red-200 inline-block disabled:opacity-50"
                        title="Delete Video"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="text-center py-12 text-slate-400">
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
        onClose={() => {
          if (!deleteMutation.isPending) {
            setIsDeleteModalOpen(false);
            setSelectedVideoId(null);
          }
        }}
        onConfirm={() => {
          if (selectedVideoId && !deleteMutation.isPending) {
            deleteMutation.mutate(selectedVideoId);
          }
        }}
        title="Delete CCTV Video Feed"
        message={`Are you sure you want to delete "${(Array.isArray(videos) ? videos.find((v: any) => v.id === selectedVideoId)?.filename : null) || 'this surveillance feed'}"? Deleting this video will permanently remove associated AI analysis data, events, and tracking indices. Continue?`}
        isLoading={deleteMutation.isPending}
      />
    </div>
  );
};
