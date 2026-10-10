import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { Video, Plus, X, Loader2, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';

export const Cameras: React.FC = () => {
  const queryClient = useQueryClient();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { register, handleSubmit, reset, formState: { errors } } = useForm();

  const { data: cameras, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['cameras-list'],
    queryFn: async () => {
      const response = await api.get('/cameras');
      return response.data || [];
    },
    staleTime: 30000,
  });

  const createMutation = useMutation({
    mutationFn: async (cameraData: any) => {
      const response = await api.post('/cameras', cameraData);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cameras-list'] });
      setIsModalOpen(false);
      reset();
    }
  });

  const onSubmit = (data: any) => {
    createMutation.mutate(data);
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <p className="animate-pulse">Loading camera catalog...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-slate-600 h-96 space-y-4">
        <p className="text-rose-600 font-medium">Failed to load camera catalog</p>
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
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Camera Management</h2>
          <p className="text-slate-500 text-sm">Register surveillance feeds, map floors, and calibrate spatial coordinates</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-xl font-semibold transition text-sm shadow-sm"
        >
          <Plus className="h-4 w-4" />
          <span>Register Camera</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {cameras && cameras.length > 0 ? (
          cameras.map((cam: any) => (
            <div key={cam.id} className="bg-white border border-slate-200 rounded-2xl p-6 hover:border-blue-500/50 hover:shadow-md transition duration-300 shadow-sm flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="bg-blue-50 p-3 rounded-xl border border-blue-100">
                    <Video className="h-6 w-6 text-blue-600" />
                  </div>
                  <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
                    cam.status === 'active' 
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200' 
                      : 'bg-slate-100 text-slate-600 border-slate-200'
                  }`}>
                    {cam.status}
                  </span>
                </div>
                <h3 className="font-semibold text-slate-900 text-lg mb-1">{cam.name}</h3>
                <p className="text-xs text-slate-500 font-mono mb-4">{cam.building} — Floor {cam.floor}</p>
                <div className="text-xs text-slate-600 space-y-1 mb-6">
                  <div className="flex justify-between"><span className="text-slate-500">Location:</span> <span className="text-slate-800 font-medium">{cam.location}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">Resolution:</span> <span className="text-slate-800 font-medium">{cam.resolution}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">Direction:</span> <span className="text-slate-800 font-medium">{cam.direction}</span></div>
                </div>
              </div>
              <Link
                to={`/cameras/${cam.id}`}
                className="w-full text-center py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-semibold transition flex items-center justify-center space-x-1"
              >
                <span>Manage Zones</span>
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          ))
        ) : (
          <div className="col-span-full text-center py-12 text-slate-400 text-sm bg-white border border-slate-200 rounded-2xl">
            No surveillance cameras currently registered.
          </div>
        )}
      </div>

      {isModalOpen && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-lg w-full p-8 shadow-2xl relative space-y-6">
            <button
              onClick={() => {
                setIsModalOpen(false);
                reset();
              }}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 transition"
            >
              <X className="h-5 w-5" />
            </button>
            
            <div>
              <h3 className="text-xl font-bold text-slate-900">Register Camera Node</h3>
              <p className="text-slate-500 text-xs">Configure physical deployment parameters</p>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Camera Name</label>
                  <input
                    type="text"
                    {...register('name', { required: 'Name is required' })}
                    placeholder="e.g. ScienceBlock-Gate01"
                    className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition text-sm"
                  />
                  {errors.name && <span className="text-xs text-red-500">{String(errors.name.message)}</span>}
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Building</label>
                  <input
                    type="text"
                    {...register('building', { required: 'Building is required' })}
                    placeholder="e.g. Science Block"
                    className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition text-sm"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Floor</label>
                  <input
                    type="number"
                    {...register('floor', { required: true, valueAsNumber: true })}
                    placeholder="1"
                    className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Direction</label>
                  <input
                    type="text"
                    {...register('direction', { required: true })}
                    placeholder="North"
                    className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Resolution</label>
                  <input
                    type="text"
                    {...register('resolution', { required: true })}
                    placeholder="1920x1080"
                    className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition text-sm"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Physical Location</label>
                <input
                  type="text"
                  {...register('location', { required: 'Location details are required' })}
                  placeholder="e.g. West Entrance Parking Lot Lobby"
                  className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition text-sm"
                />
              </div>

              <button
                type="submit"
                disabled={createMutation.isPending}
                className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold shadow-sm transition flex items-center justify-center space-x-2 text-sm pt-2"
              >
                {createMutation.isPending ? (
                  <>
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span>Registering Camera...</span>
                  </>
                ) : (
                  <span>Register Camera</span>
                )}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
