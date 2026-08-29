import React, { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { Upload, Film, Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export const UploadFeed: React.FC = () => {
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
    onSuccess: () => {
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
        <h2 className="text-2xl font-bold text-slate-100">Ingest CCTV Feed</h2>
        <p className="text-slate-400 text-sm">Upload surveillance footage to run detection, tracking and identification models</p>
      </div>

      <form onSubmit={handleUpload} className="bg-dark-card border border-dark-border rounded-2xl p-8 shadow-xl space-y-6">
        {mutation.error && (
          <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg p-3 text-center">
            Upload failed: {(mutation.error as any).response?.data?.detail || "Make sure file is a valid video format."}
          </div>
        )}

        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Feed Title / Camera Label</label>
          <input
            type="text"
            placeholder="e.g. Science Block West Gate"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full px-4 py-3 bg-slate-900 border border-dark-border rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition text-sm"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Associate Camera Source</label>
          <select
            value={cameraId}
            onChange={(e) => setCameraId(e.target.value)}
            className="w-full px-4 py-3 bg-slate-900 border border-dark-border rounded-xl text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm"
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
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Select Video Asset</label>
          <div className="border-2 border-dashed border-dark-border rounded-2xl p-8 text-center hover:border-blue-500 transition relative flex flex-col items-center justify-center bg-slate-900/20">
            <input
              type="file"
              accept="video/*"
              onChange={handleFileChange}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            />
            {file ? (
              <div className="space-y-2">
                <div className="bg-blue-600/10 p-3 rounded-xl border border-blue-500/20 inline-block">
                  <Film className="h-8 w-8 text-blue-500" />
                </div>
                <p className="font-semibold text-slate-300 text-sm">{file.name}</p>
                <p className="text-xs text-slate-500">{(file.size / (1024 * 1024)).toFixed(1)} MB</p>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="bg-slate-800 p-3 rounded-xl inline-block">
                  <Upload className="h-8 w-8 text-slate-400" />
                </div>
                <p className="font-semibold text-slate-300 text-sm">Click or drag video file here</p>
                <p className="text-xs text-slate-500">MP4, AVI, or MKV formats</p>
              </div>
            )}
          </div>
        </div>

        <button
          type="submit"
          disabled={!file || mutation.isPending}
          className="w-full py-3 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-500 text-white rounded-xl font-semibold shadow-lg shadow-blue-500/20 transition flex items-center justify-center space-x-2 text-sm"
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
