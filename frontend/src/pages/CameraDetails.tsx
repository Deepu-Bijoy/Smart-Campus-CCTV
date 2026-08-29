import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { VirtualZoneEditor } from '../components/VirtualZoneEditor';
import { Video, ShieldAlert, Trash2, ArrowLeft } from 'lucide-react';

export const CameraDetails: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

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
      await api.delete(`/cameras/${id}/zones/${zoneId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['camera-detail', id] });
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
          className="flex items-center space-x-2 text-slate-400 hover:text-slate-200 transition text-sm font-semibold"
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
          className="bg-red-600/10 hover:bg-red-600/20 text-red-500 hover:text-red-400 border border-red-500/20 px-4 py-2 rounded-xl text-xs font-bold transition"
        >
          Decommission Camera
        </button>
      </div>

      {/* Summary card */}
      <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md flex items-center space-x-5">
        <div className="bg-blue-600/10 p-4 rounded-xl border border-blue-500/20">
          <Video className="h-8 w-8 text-blue-500" />
        </div>
        <div>
          <h2 className="text-2xl font-bold text-slate-100">{camera?.name}</h2>
          <p className="text-slate-400 text-xs mt-0.5">{camera?.building} — Floor {camera?.floor} ({camera?.location})</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <VirtualZoneEditor
            onSave={(zone) => addZoneMutation.mutate(zone)}
          />
        </div>

        {/* Existing zones list */}
        <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
          <div className="flex items-center space-x-2 text-slate-300 font-semibold border-b border-dark-border pb-3 mb-2">
            <ShieldAlert className="h-4 w-4 text-blue-500" />
            <span>Virtual Intrusion Boundaries</span>
          </div>

          <div className="space-y-3">
            {camera?.zones && camera.zones.length > 0 ? (
              camera.zones.map((zone: any) => (
                <div key={zone.id} className="bg-slate-900/50 border border-dark-border rounded-xl p-4 flex items-center justify-between">
                  <div>
                    <h4 className="font-semibold text-slate-200 text-sm">{zone.name}</h4>
                    <div className="flex items-center space-x-2 mt-1.5">
                      <span className="text-[10px] bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded-full uppercase tracking-wider font-bold">
                        {zone.zone_type}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono capitalize">
                        {zone.geometry_type}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => deleteZoneMutation.mutate(zone.id)}
                    className="text-slate-500 hover:text-red-400 transition p-1 rounded hover:bg-red-500/10 border border-transparent"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))
            ) : (
              <div className="text-center py-8 text-slate-500 text-sm">
                No virtual zones defined for this camera footprint.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
