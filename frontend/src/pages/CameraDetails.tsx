import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { VirtualZoneEditor } from '../components/VirtualZoneEditor';
import { Video, ShieldAlert, Trash2, ArrowLeft, AlertCircle } from 'lucide-react';

export const CameraDetails: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deletingZoneId, setDeletingZoneId] = useState<string | null>(null);

  const { data: camera, isLoading } = useQuery({
    queryKey: ['camera-detail', id],
    queryFn: async () => {
      const response = await api.get(`/cameras/${id}`);
      return response.data;
    }
  });

  const addZoneMutation = useMutation({
    mutationFn: async (zoneData: any) => {
      const response = await api.post(`/cameras/${id}/zones`, {
        name: zoneData.name,
        zone_type: zoneData.zoneType,
        geometry_type: zoneData.geometryType,
        coordinates: zoneData.coordinates
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['camera-detail', id] });
    }
  });

  const deleteZoneMutation = useMutation({
    mutationFn: async (zoneId: string) => {
      setDeletingZoneId(zoneId);
      setDeleteError(null);
      await api.delete(`/cameras/${id}/zones/${zoneId}`);
    },
    retry: false,
    onSuccess: () => {
      setDeletingZoneId(null);
      setDeleteError(null);
      queryClient.invalidateQueries({ queryKey: ['camera-detail', id] });
    },
    onError: (err: any) => {
      setDeletingZoneId(null);
      const msg = err.response?.data?.detail || err.message || 'Failed to delete virtual boundary zone.';
      setDeleteError(msg);
    }
  });

  const deleteCameraMutation = useMutation({
    mutationFn: async () => {
      await api.delete(`/cameras/${id}`);
    },
    onSuccess: () => {
      navigate('/cameras');
    }
  });

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <p className="animate-pulse">Loading camera details...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 py-2">
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate('/cameras')}
          className="flex items-center space-x-2 text-slate-600 hover:text-slate-900 transition text-sm font-semibold"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Catalog</span>
        </button>
        <button
          onClick={() => {
            if (confirm('Permanently delete this camera and related virtual zones?')) {
              deleteCameraMutation.mutate();
            }
          }}
          className="bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 px-4 py-2 rounded-xl text-xs font-bold transition"
        >
          Decommission Camera
        </button>
      </div>

      {/* Summary card */}
      <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm flex items-center space-x-5">
        <div className="bg-blue-50 p-4 rounded-xl border border-blue-100">
          <Video className="h-8 w-8 text-blue-600" />
        </div>
        <div>
          <h2 className="text-2xl font-bold text-slate-900">{camera?.name}</h2>
          <p className="text-slate-500 text-xs mt-0.5">{camera?.building} — Floor {camera?.floor} ({camera?.location})</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <VirtualZoneEditor
            onSave={(zone) => addZoneMutation.mutate(zone)}
          />
        </div>

        {/* Existing zones list */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-4">
          <div className="flex items-center space-x-2 text-slate-900 font-semibold border-b border-slate-200 pb-3 mb-2">
            <ShieldAlert className="h-4 w-4 text-blue-600" />
            <span>Virtual Intrusion Boundaries</span>
          </div>

          {deleteError && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-xl text-xs flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <AlertCircle className="h-3.5 w-3.5 flex-shrink-0 text-red-500" />
                <span>{deleteError}</span>
              </div>
              <button
                onClick={() => setDeleteError(null)}
                className="text-red-500 hover:text-red-700 font-bold ml-2 text-xs"
                title="Dismiss error"
              >
                ✕
              </button>
            </div>
          )}

          <div className="space-y-3">
            {camera?.zones && camera.zones.length > 0 ? (
              camera.zones.map((zone: any) => {
                const isDeleting = deletingZoneId === zone.id;
                return (
                  <div key={zone.id} className="bg-slate-50 border border-slate-200 rounded-xl p-4 flex items-center justify-between">
                    <div>
                      <h4 className="font-semibold text-slate-900 text-sm">{zone.name}</h4>
                      <div className="flex items-center space-x-2 mt-1.5">
                        <span className="text-[10px] bg-blue-50 text-blue-700 border border-blue-200 px-2 py-0.5 rounded-full uppercase tracking-wider font-bold">
                          {zone.zone_type}
                        </span>
                        <span className="text-[10px] text-slate-500 font-mono capitalize">
                          {zone.geometry_type}
                        </span>
                      </div>
                    </div>
                    <button
                      disabled={deleteZoneMutation.isPending}
                      onClick={() => {
                        if (deleteZoneMutation.isPending) return;
                        deleteZoneMutation.mutate(zone.id);
                      }}
                      className={`p-1.5 rounded transition border border-transparent ${
                        isDeleting
                          ? 'text-slate-300 cursor-not-allowed bg-slate-100'
                          : deleteZoneMutation.isPending
                          ? 'text-slate-300 cursor-not-allowed'
                          : 'text-slate-400 hover:text-red-600 hover:bg-red-50'
                      }`}
                      title="Delete virtual intrusion boundary"
                    >
                      <Trash2 className={`h-4 w-4 ${isDeleting ? 'animate-pulse text-red-400' : ''}`} />
                    </button>
                  </div>
                );
              })
            ) : (
              <div className="text-center py-8 text-slate-400 text-sm">
                No virtual zones defined for this camera footprint.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
