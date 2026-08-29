import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { SearchBar } from '../components/SearchBar';
import { StudentCard } from '../components/StudentCard';
import type { StudentData } from '../components/StudentCard';
import { Plus, X, Loader2, ArrowLeft, ArrowRight } from 'lucide-react';
import { useForm } from 'react-hook-form';

export const Students: React.FC = () => {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  const [isModalOpen, setIsModalOpen] = useState(false);
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

  const registerMutation = useMutation({
    mutationFn: async (studentData: any) => {
      const response = await api.post('/students', studentData);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['students-list'] });
      setIsModalOpen(false);
      reset();
    }
  });

  const onSubmit = (data: any) => {
    registerMutation.mutate(data);
  };

  const total = data?.total ?? 0;
  const items = (data?.items ?? []) as StudentData[];
  const totalPages = Math.ceil(total / limit);

  return (
    <div className="space-y-8 py-2">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-100">Student Directory</h2>
          <p className="text-slate-400 text-sm">Enrolled targets, class records, and metadata indices</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-500 text-white px-5 py-2.5 rounded-xl font-semibold transition text-sm shadow-lg shadow-blue-500/15"
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
                <StudentCard key={student.id} student={student} />
              ))
            ) : (
              <div className="col-span-full text-center py-12 text-slate-500 text-sm bg-dark-card border border-dark-border rounded-2xl">
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
                className="p-2.5 bg-dark-card border border-dark-border text-slate-300 hover:text-white rounded-lg disabled:opacity-50 transition"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
              <span className="text-sm font-semibold text-slate-400">Page {page} of {totalPages}</span>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="p-2.5 bg-dark-card border border-dark-border text-slate-300 hover:text-white rounded-lg disabled:opacity-50 transition"
              >
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </>
      )}

      {/* Registration Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-dark-card border border-dark-border rounded-2xl max-w-lg w-full p-8 shadow-2xl relative space-y-6">
            <button
              onClick={() => {
                setIsModalOpen(false);
                reset();
              }}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-200 transition"
            >
              <X className="h-5 w-5" />
            </button>
            
            <div>
              <h3 className="text-xl font-bold text-slate-100">Enroll Student Profile</h3>
              <p className="text-slate-400 text-xs">Fill out university enrollment details</p>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Full Name</label>
                  <input
                    type="text"
                    {...register('name', { required: 'Name is required' })}
                    placeholder="Jane Doe"
                    className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm"
                  />
                  {errors.name && <span className="text-xs text-red-400">{String(errors.name.message)}</span>}
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Roll Number</label>
                  <input
                    type="text"
                    {...register('university_roll_number', { required: 'Roll number is required' })}
                    placeholder="UR202611"
                    className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm"
                  />
                  {errors.university_roll_number && <span className="text-xs text-red-400">{String(errors.university_roll_number.message)}</span>}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Department</label>
                  <input
                    type="text"
                    {...register('department', { required: 'Department is required' })}
                    placeholder="Computer Science"
                    className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Programme</label>
                  <input
                    type="text"
                    {...register('programme', { required: 'Programme is required' })}
                    placeholder="B.Tech"
                    className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Year</label>
                  <input
                    type="number"
                    {...register('year', { required: true, valueAsNumber: true })}
                    placeholder="3"
                    className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Semester</label>
                  <input
                    type="number"
                    {...register('semester', { required: true, valueAsNumber: true })}
                    placeholder="6"
                    className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Section</label>
                  <input
                    type="text"
                    {...register('section')}
                    placeholder="A"
                    className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Email Address</label>
                <input
                  type="email"
                  {...register('email', { required: 'Email is required' })}
                  placeholder="jane@university.edu"
                  className="w-full px-3 py-2 bg-slate-900 border border-dark-border rounded-lg text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm"
                />
              </div>

              <button
                type="submit"
                disabled={registerMutation.isPending}
                className="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-semibold shadow-lg shadow-blue-500/20 transition flex items-center justify-center space-x-2 text-sm pt-2"
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
    </div>
  );
};
