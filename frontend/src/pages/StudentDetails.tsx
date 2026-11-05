import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { User, Award, Shield, UploadCloud, Cpu, AlertCircle, CheckCircle2, RefreshCw, Eye, Trash2 } from 'lucide-react';
import { DeleteConfirmationModal } from '../components/DeleteConfirmationModal';
import { AuthenticatedImage } from '../components/AuthenticatedImage';

export const StudentDetails: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [selectedFiles, setSelectedFiles] = useState<FileList | null>(null);
  const [photoView, setPhotoView] = useState('front');

  const [deleteError, setDeleteError] = useState<string | null>(null);

  const { data: student, isLoading: isStudentLoading, isError: isStudentError } = useQuery({
    queryKey: ['student', id],
    queryFn: async () => {
      const res = await api.get(`/students/${id}`);
      return res.data;
    },
    retry: (failureCount, error: any) => {
      const status = error?.response?.status || error?.status;
      if (status >= 400 && status < 500) return false;
      return failureCount < 1;
    }
  });

  const isStudentReady = Boolean(student && !isStudentError && id);

  const { data: photos } = useQuery({
    queryKey: ['student-photos', id],
    queryFn: async () => {
      const res = await api.get(`/students/${id}/photos`);
      return res.data;
    },
    enabled: isStudentReady,
    retry: false
  });

  const { data: statusData, refetch: refetchStatus } = useQuery({
    queryKey: ['student-enrollment-status', id],
    queryFn: async () => {
      const res = await api.get(`/students/${id}/enrollment-status`);
      return res.data;
    },
    enabled: isStudentReady,
    retry: false
  });

  const { data: appearances } = useQuery({
    queryKey: ['student-appearances', id],
    queryFn: async () => {
      const res = await api.get(`/students/${id}/appearances`);
      return res.data;
    },
    enabled: isStudentReady,
    retry: false
  });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!selectedFiles) return;
      const formData = new FormData();
      for (let i = 0; i < selectedFiles.length; i++) {
        formData.append('files', selectedFiles[i]);
      }
      formData.append('views', photoView);
      
      const res = await api.post(`/students/${id}/photos`, formData);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['student-photos', id] });
      queryClient.invalidateQueries({ queryKey: ['student-enrollment-status', id] });
      setSelectedFiles(null);
    }
  });

  const enrollMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post(`/students/${id}/enroll`);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['student-enrollment-status', id] });
      refetchStatus();
      alert('Face enrollment pipeline executed successfully!');
    },
    onError: (err: any) => {
      alert(`Enrollment failed: ${err.response?.data?.detail || err.message}`);
    }
  });

  const navigate = useNavigate();
  const [isPhotoDeleteModalOpen, setIsPhotoDeleteModalOpen] = useState(false);
  const [selectedPhotoId, setSelectedPhotoId] = useState<string | null>(null);
  const [isStudentDeleteModalOpen, setIsStudentDeleteModalOpen] = useState(false);

  const deletePhotoMutation = useMutation({
    mutationFn: async (photoId: string) => {
      await api.delete(`/students/${id}/photos/${photoId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['student-photos', id] });
      queryClient.invalidateQueries({ queryKey: ['student-enrollment-status', id] });
      refetchStatus();
      setIsPhotoDeleteModalOpen(false);
      setSelectedPhotoId(null);
    },
    onError: (err: any) => {
      alert(`Failed to delete photo: ${err.response?.data?.detail || err.message}`);
    }
  });

  const deleteStudentMutation = useMutation({
    mutationFn: async () => {
      setDeleteError(null);
      await api.delete(`/students/${id}`);
      return id;
    },
    retry: false,
    onMutate: async () => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ['student', id] }),
        queryClient.cancelQueries({ queryKey: ['student-photos', id] }),
        queryClient.cancelQueries({ queryKey: ['student-enrollment-status', id] }),
        queryClient.cancelQueries({ queryKey: ['student-appearances', id] }),
      ]);
    },
    onSuccess: () => {
      setIsStudentDeleteModalOpen(false);
      queryClient.removeQueries({ queryKey: ['student', id] });
      queryClient.removeQueries({ queryKey: ['student-photos', id] });
      queryClient.removeQueries({ queryKey: ['student-enrollment-status', id] });
      queryClient.removeQueries({ queryKey: ['student-appearances', id] });

      queryClient.setQueriesData({ queryKey: ['students-list'] }, (old: any) => {
        if (!old) return old;
        if (Array.isArray(old)) {
          return old.filter((s: any) => s.id !== id);
        }
        if (old.items && Array.isArray(old.items)) {
          return {
            ...old,
            total: Math.max(0, (old.total || 1) - 1),
            items: old.items.filter((s: any) => s.id !== id),
          };
        }
        return old;
      });

      queryClient.invalidateQueries({ queryKey: ['students-list'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] });
      navigate('/students', { replace: true });
    },
    onError: (err: any) => {
      const msg = err.response?.data?.detail || err.message || 'Failed to delete student.';
      setDeleteError(msg);
      setIsStudentDeleteModalOpen(false);
    }
  });

  if (isStudentLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <p className="animate-pulse">Loading profile details...</p>
      </div>
    );
  }

  if (isStudentError) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-slate-600 h-96 space-y-4">
        <AlertCircle className="h-12 w-12 text-rose-500" />
        <h3 className="text-lg font-bold text-slate-900">Student Profile Not Found</h3>
        <p className="text-sm text-slate-500 max-w-md text-center">
          The requested student record does not exist or has been deleted.
        </p>
        <button
          onClick={() => navigate('/students', { replace: true })}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold transition shadow-sm"
        >
          Return to Student Directory
        </button>
      </div>
    );
  }

  const enrolledViews = statusData?.enrolled_views || [];
  const missingViews = statusData?.missing_views || [];

  return (
    <div className="space-y-8 py-2">
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

      {/* Header Profile Summary */}
      <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="flex items-center space-x-5">
          <div className="bg-blue-50 p-5 rounded-2xl border border-blue-100">
            <User className="h-10 w-10 text-blue-600" />
          </div>
          <div>
            <h2 className="text-2xl font-bold text-slate-900">{student?.name}</h2>
            <p className="text-slate-600 font-mono text-sm mt-0.5">{student?.university_roll_number}</p>
            <div className="flex items-center space-x-4 mt-3 text-xs text-slate-500">
              <span className="flex items-center space-x-1">
                <Award className="h-4 w-4 text-slate-400" />
                <span>{student?.department}</span>
              </span>
              <span className="flex items-center space-x-1">
                <Shield className="h-4 w-4 text-slate-400" />
                <span>{student?.programme} • Year {student?.year}</span>
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={() => enrollMutation.mutate()}
            disabled={enrollMutation.isPending || !photos || photos.length === 0}
            className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-100 disabled:text-slate-400 text-white px-5 py-2.5 rounded-xl font-semibold transition text-sm shadow-sm"
          >
            {enrollMutation.isPending ? (
              <>
                <RefreshCw className="h-4 w-4 animate-spin" />
                <span>Generating Embeddings...</span>
              </>
            ) : (
              <>
                <Cpu className="h-4 w-4" />
                <span>Trigger Face Enrollment</span>
              </>
            )}
          </button>
          
          <button
            onClick={() => setIsStudentDeleteModalOpen(true)}
            disabled={deleteStudentMutation.isPending}
            className="flex items-center space-x-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white px-5 py-2.5 rounded-xl font-semibold transition text-sm shadow-sm"
          >
            <Trash2 className="h-4 w-4" />
            <span>{deleteStudentMutation.isPending ? 'Deleting...' : 'Delete Student'}</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          {/* Photo Gallery */}
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
            <h3 className="font-bold text-slate-900 text-lg mb-6">Uploaded Photo Angles</h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              {photos && photos.length > 0 ? (
                photos.map((photo: any) => (
                  <div key={photo.id} className="border border-slate-200 rounded-xl overflow-hidden bg-slate-100 relative group aspect-square shadow-sm">
                    <AuthenticatedImage
                      src={`/storage/${photo.photo_path.replace(/\\/g, '/').replace(/^\/+/, '').replace(/^storage\//, '')}`}
                      alt={photo.view}
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent flex flex-col justify-end p-3">
                      <span className="text-xs font-semibold text-white capitalize bg-blue-600 px-2 py-0.5 rounded w-fit">
                        {photo.view}
                      </span>
                      <span className="text-[10px] text-slate-300 mt-1 font-mono">{(photo.file_size / 1024).toFixed(0)} KB</span>
                    </div>
                    <button
                      onClick={() => {
                        setSelectedPhotoId(photo.id);
                        setIsPhotoDeleteModalOpen(true);
                      }}
                      className="absolute top-2 right-2 bg-red-600 hover:bg-red-700 p-1.5 rounded-lg text-white opacity-0 group-hover:opacity-100 transition duration-150 shadow"
                      title="Delete Photo"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))
              ) : (
                <div className="col-span-full text-center py-12 text-slate-500 text-sm">
                  No profile photos uploaded yet.
                </div>
              )}
            </div>
          </div>

          {/* Appearances */}
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
            <h3 className="font-bold text-slate-900 text-lg mb-6">CCTV Appearances History</h3>
            <div className="divide-y divide-slate-100">
              {appearances && appearances.length > 0 ? (
                appearances.map((app: any) => (
                  <div key={app.event_id} className="py-4 flex items-center justify-between first:pt-0 last:pb-0">
                    <div className="flex items-center space-x-3">
                      <Eye className="h-5 w-5 text-blue-600" />
                      <div>
                        <h4 className="font-semibold text-slate-800 text-sm">Identified on Camera: {app.camera_id}</h4>
                        <p className="text-xs text-slate-500 mt-0.5">{new Date(app.timestamp).toLocaleString()}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
                        app.confidence === 'high'
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                          : 'bg-amber-50 text-amber-700 border-amber-200'
                      }`}>
                        {(app.similarity_score * 100).toFixed(0)}% Match ({app.confidence})
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-12 text-slate-500 text-sm">
                  No CCTV recognition occurrences detected yet.
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          {/* Enrollment status */}
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-4">
            <h3 className="font-bold text-slate-900 text-lg">Enrollment Diagnostic</h3>
            
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <span className="text-xs text-slate-500">Total Vectors Index</span>
                <span className="font-mono text-slate-900 font-semibold">{statusData?.embeddings_count ?? 0}</span>
              </div>
              
              <div className="space-y-2">
                <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider block">Indexed Views ({enrolledViews.length})</span>
                <div className="flex flex-wrap gap-1.5">
                  {enrolledViews.map((v: string) => (
                    <span key={v} className="flex items-center space-x-1 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full capitalize">
                      <CheckCircle2 className="h-3 w-3" />
                      <span>{v}</span>
                    </span>
                  ))}
                </div>
              </div>

              {missingViews.length > 0 && (
                <div className="space-y-2">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider block">Missing Views ({missingViews.length})</span>
                  <div className="flex flex-wrap gap-1.5">
                    {missingViews.map((v: string) => (
                      <span key={v} className="flex items-center space-x-1 text-xs bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-full capitalize">
                        <AlertCircle className="h-3 w-3" />
                        <span>{v}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Upload panel */}
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-6">
            <h3 className="font-bold text-slate-900 text-lg">Upload Face Photos</h3>
            <form onSubmit={(e) => { e.preventDefault(); uploadMutation.mutate(); }} className="space-y-4">
              <div className="space-y-1">
                <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Photo View Angle</label>
                <select
                  value={photoView}
                  onChange={(e) => setPhotoView(e.target.value)}
                  className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition capitalize"
                >
                  {['front', 'left', 'right', 'up', 'down', 'masked', 'glasses'].map(view => (
                    <option key={view} value={view}>{view}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Select Files</label>
                <input
                  type="file"
                  multiple
                  accept="image/jpeg,image/png"
                  onChange={(e) => setSelectedFiles(e.target.files)}
                  className="w-full text-xs text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200 cursor-pointer"
                />
              </div>

              <button
                type="submit"
                disabled={!selectedFiles || uploadMutation.isPending}
                className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-100 disabled:text-slate-400 text-white rounded-xl font-semibold shadow-sm transition flex items-center justify-center space-x-2 text-sm"
              >
                {uploadMutation.isPending ? (
                  <>
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    <span>Uploading Photos...</span>
                  </>
                ) : (
                  <>
                    <UploadCloud className="h-4 w-4" />
                    <span>Upload Attachments</span>
                  </>
                )}
              </button>
            </form>
          </div>
        </div>
      </div>

      <DeleteConfirmationModal
        isOpen={isPhotoDeleteModalOpen}
        onClose={() => { setIsPhotoDeleteModalOpen(false); setSelectedPhotoId(null); }}
        onConfirm={() => { if (selectedPhotoId) deletePhotoMutation.mutate(selectedPhotoId); }}
        title="Delete Photo"
        message="Are you sure you want to delete this photo?"
        isLoading={deletePhotoMutation.isPending}
      />

      <DeleteConfirmationModal
        isOpen={isStudentDeleteModalOpen}
        onClose={() => {
          if (!deleteStudentMutation.isPending) {
            setIsStudentDeleteModalOpen(false);
          }
        }}
        onConfirm={() => {
          if (!deleteStudentMutation.isPending) {
            deleteStudentMutation.mutate();
          }
        }}
        title="Delete Student Record"
        message="Deleting this student will remove all face embeddings, recognition occurrences, photos, and timelines. Continue?"
        isLoading={deleteStudentMutation.isPending}
      />
    </div>
  );
};
