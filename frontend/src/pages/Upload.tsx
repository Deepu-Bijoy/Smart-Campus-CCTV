import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { Upload, Film, Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export const UploadFeed: React.FC = () => {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [cameraId, setCameraId] = useState('');
  const navigate = useNavigate();

  const { data: cameras } = useQuery({
    queryKey: ['cameras-list'],
    queryFn: async () => {
      const response = await api.get('/cameras');
      return response.data || [];
    }
  });

  const mutation = useMutation({
    mutationFn: async () => {
      if (!file) return;
      const formData = new FormData();
      formData.append('file', file);
      if (title) {
        formData.append('title', title);
      }
      if (cameraId) {
        formData.append('camera_id', cameraId);
      }
      const response = await api.post('/videos/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      return response.data;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['videos-list'] }),
        queryClient.invalidateQueries({ queryKey: ['recent-videos'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] }),
      ]);
      navigate('/videos');
    }
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const handleUpload = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  return (
    <div className="max-w-2xl mx-auto py-4 space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Ingest CCTV Feed</h2>
        <p className="text-slate-500 text-sm">Upload surveillance footage to run detection, tracking and identification models</p>
      </div>

      <form onSubmit={handleUpload} className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm space-y-6">
        {mutation.error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 text-center">
            Upload failed: {(mutation.error as any).response?.data?.detail || "Make sure file is a valid video format."}
          </div>
        )}

        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Feed Title / Camera Label</label>
          <input
            type="text"
            placeholder="e.g. Science Block West Gate"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-slate-900 placeholder-slate-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition text-sm"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Associate Camera Source</label>
          <select
            value={cameraId}
            onChange={(e) => setCameraId(e.target.value)}
            className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition text-sm"
          >
            <option value="">Select Camera...</option>
            {cameras?.map((cam: any) => (
              <option key={cam.id} value={cam.id}>
                {cam.name} ({cam.location})
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Select Video Asset</label>
          <div className="border-2 border-dashed border-slate-300 rounded-2xl p-8 text-center hover:border-blue-500 transition relative flex flex-col items-center justify-center bg-slate-50/50">
            <input
              type="file"
              accept="video/*"
              onChange={handleFileChange}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            />
            {file ? (
              <div className="space-y-2">
                <div className="bg-blue-50 p-3 rounded-xl border border-blue-100 inline-block">
                  <Film className="h-8 w-8 text-blue-600" />
                </div>
                <p className="font-semibold text-slate-900 text-sm">{file.name}</p>
                <p className="text-xs text-slate-500">{(file.size / (1024 * 1024)).toFixed(1)} MB</p>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="bg-slate-100 p-3 rounded-xl inline-block">
                  <Upload className="h-8 w-8 text-slate-500" />
                </div>
                <p className="font-semibold text-slate-700 text-sm">Click or drag video file here</p>
                <p className="text-xs text-slate-400">MP4, AVI, or MKV formats</p>
              </div>
            )}
          </div>
        </div>

        <button
          type="submit"
          disabled={!file || mutation.isPending}
          className="w-full py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 text-white rounded-xl font-semibold shadow-sm transition flex items-center justify-center space-x-2 text-sm"
        >
          {mutation.isPending ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin" />
              <span>Uploading & Processing Feed...</span>
            </>
          ) : (
            <span>Ingest Surveillance Video</span>
          )}
        </button>
      </form>
    </div>
  );
};
