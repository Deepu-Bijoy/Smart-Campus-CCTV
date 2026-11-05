import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { SearchBar } from '../components/SearchBar';
import { StudentCard } from '../components/StudentCard';
import type { StudentData } from '../components/StudentCard';
import { Plus, X, Loader2, ArrowLeft, ArrowRight } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { DeleteConfirmationModal } from '../components/DeleteConfirmationModal';

export const Students: React.FC = () => {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [studentToDelete, setStudentToDelete] = useState<StudentData | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { register, handleSubmit, reset, formState: { errors } } = useForm();
  const limit = 6;

  const { data, isLoading } = useQuery({
    queryKey: ['students-list', searchQuery, page],
    queryFn: async () => {
      const skip = (page - 1) * limit;
      const response = await api.get('/students', {
        params: {
          search: searchQuery || undefined,
          skip,
          limit,
          sort_by: 'created_at',
          sort_order: 'desc'
        }
      });
      return response.data;
    }
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      setDeleteError(null);
      await api.delete(`/students/${id}`);
      return id;
    },
    retry: false,
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: ['students-list'] });
      const previousData = queryClient.getQueryData(['students-list', searchQuery, page]);

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

      return { previousData };
    },
    onSuccess: () => {
      setIsDeleteModalOpen(false);
      setStudentToDelete(null);
      setDeleteError(null);
      queryClient.invalidateQueries({ queryKey: ['students-list'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] });
    },
    onError: (err: any, _id: string, context: any) => {
      if (context?.previousData) {
        queryClient.setQueryData(['students-list', searchQuery, page], context.previousData);
      }
      const msg = err.response?.data?.detail || err.message || 'Failed to delete student.';
      setDeleteError(msg);
      setIsDeleteModalOpen(false);
      setStudentToDelete(null);
    }
  });

  const registerMutation = useMutation({
    mutationFn: async (studentData: any) => {
      const response = await api.post('/students', studentData);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['students-list'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] });
      setIsModalOpen(false);
      setFormError(null);
      reset();
    },
    onError: (err: any) => {
      let msg = 'Failed to register student profile.';
      if (err.response?.data?.detail) {
        if (Array.isArray(err.response.data.detail)) {
          msg = err.response.data.detail.map((d: any) => `${d.loc?.slice(-1)[0] || 'Field'}: ${d.msg}`).join(', ');
        } else if (typeof err.response.data.detail === 'string') {
          msg = err.response.data.detail;
        }
      } else if (err.message) {
        msg = err.message;
      }
      setFormError(msg);
    }
  });

  const onSubmit = (data: any) => {
    setFormError(null);
    registerMutation.mutate(data);
  };

  const total = data?.total ?? 0;
  const items = (data?.items ?? []) as StudentData[];
  const totalPages = Math.ceil(total / limit);

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

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Student Directory</h2>
          <p className="text-slate-500 text-sm">Enrolled targets, class records, and metadata indices</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-xl font-semibold transition text-sm shadow-sm"
        >
          <Plus className="h-4 w-4" />
          <span>Register Student</span>
        </button>
      </div>

      {/* Search */}
      <div className="max-w-md">
        <SearchBar
          placeholder="Search by name, roll number, or email..."
          value={searchQuery}
          onChange={(val) => {
            setSearchQuery(val);
            setPage(1);
          }}
        />
      </div>

      {isLoading ? (
        <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
          <p className="animate-pulse">Loading student database...</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {items.length > 0 ? (
              items.map((student) => (
                <StudentCard
                  key={student.id}
                  student={student}
                  onDelete={(s) => {
                    setStudentToDelete(s);
                    setIsDeleteModalOpen(true);
                  }}
                />
              ))
            ) : (
              <div className="col-span-full text-center py-12 text-slate-500 text-sm bg-white border border-slate-200 rounded-2xl shadow-sm">
                No matching student records found.
              </div>
            )}
          </div>

          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center space-x-4 pt-4">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-2.5 bg-white border border-slate-200 text-slate-600 hover:text-slate-900 rounded-lg disabled:opacity-40 transition shadow-sm"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
              <span className="text-sm font-semibold text-slate-600">Page {page} of {totalPages}</span>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="p-2.5 bg-white border border-slate-200 text-slate-600 hover:text-slate-900 rounded-lg disabled:opacity-40 transition shadow-sm"
              >
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </>
      )}

      {/* Registration Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-lg w-full p-8 shadow-xl relative space-y-6">
            <button
              onClick={() => {
                setIsModalOpen(false);
                setFormError(null);
                reset();
              }}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 transition"
            >
              <X className="h-5 w-5" />
            </button>
            
            <div>
              <h3 className="text-xl font-bold text-slate-900">Enroll Student Profile</h3>
              <p className="text-slate-500 text-xs">Fill out university enrollment details</p>
            </div>

            {formError && (
              <div className="p-3 bg-red-50 border border-red-200 text-red-600 text-xs rounded-xl flex items-center space-x-2">
                <span>{formError}</span>
              </div>
            )}

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Full Name</label>
                  <input
                    type="text"
                    {...register('name', { required: 'Name is required' })}
                    placeholder="Jane Doe"
                    className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition text-sm"
                  />
                  {errors.name && <span className="text-xs text-red-600">{String(errors.name.message)}</span>}
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Roll Number</label>
                  <input
                    type="text"
                    {...register('university_roll_number', { required: 'Roll number is required' })}
                    placeholder="UR202611"
                    className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition text-sm"
                  />
                  {errors.university_roll_number && <span className="text-xs text-red-600">{String(errors.university_roll_number.message)}</span>}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Department</label>
                  <input
                    type="text"
                    {...register('department', { required: 'Department is required' })}
                    placeholder="Computer Science"
                    className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition text-sm"
                  />
                  {errors.department && <span className="text-xs text-red-600">{String(errors.department.message)}</span>}
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Programme</label>
                  <input
                    type="text"
                    {...register('programme', { required: 'Programme is required' })}
                    placeholder="B.Tech"
                    className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition text-sm"
                  />
                  {errors.programme && <span className="text-xs text-red-600">{String(errors.programme.message)}</span>}
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Year</label>
                  <input
                    type="number"
                    {...register('year', { required: true, valueAsNumber: true })}
                    placeholder="3"
                    className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Semester</label>
                  <input
                    type="number"
                    {...register('semester', { required: true, valueAsNumber: true })}
                    placeholder="6"
                    className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Section</label>
                  <input
                    type="text"
                    {...register('section', { required: 'Section is required' })}
                    placeholder="A"
                    className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition text-sm"
                  />
                  {errors.section && <span className="text-xs text-red-600">{String(errors.section.message)}</span>}
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Email Address</label>
                <input
                  type="email"
                  {...register('email', { required: 'Email is required' })}
                  placeholder="jane@university.edu"
                  className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition text-sm"
                />
                {errors.email && <span className="text-xs text-red-600">{String(errors.email.message)}</span>}
              </div>

              <button
                type="submit"
                disabled={registerMutation.isPending}
                className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold shadow-sm transition flex items-center justify-center space-x-2 text-sm pt-2"
              >
                {registerMutation.isPending ? (
                  <>
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span>Registering Profile...</span>
                  </>
                ) : (
                  <span>Register Profile</span>
                )}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <DeleteConfirmationModal
        isOpen={isDeleteModalOpen}
        onClose={() => {
          if (!deleteMutation.isPending) {
            setIsDeleteModalOpen(false);
            setStudentToDelete(null);
          }
        }}
        onConfirm={() => {
          if (studentToDelete && !deleteMutation.isPending) {
            deleteMutation.mutate(studentToDelete.id);
          }
        }}
        title="Delete Student Record"
        message={`Are you sure you want to delete "${studentToDelete?.name || 'this student'}"? Deleting this student will remove all face embeddings, recognition occurrences, photos, and timelines. Continue?`}
        isLoading={deleteMutation.isPending}
      />
    </div>
  );
};
