import React from 'react';
import { useForm } from 'react-hook-form';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/useAuthStore';
import { api } from '../services/api';
import { Lock, Mail, Loader2 } from 'lucide-react';

export const Login: React.FC = () => {
  const { register, handleSubmit, setError, formState: { errors } } = useForm();
  const setAuth = useAuthStore(state => state.setAuth);
  const navigate = useNavigate();

  const mutation = useMutation({
    mutationFn: async (data: any) => {
      const params = new URLSearchParams();
      params.append('username', data.email);
      params.append('password', data.password);
      
      const response = await api.post('/auth/login', params, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      return response.data;
    },
    onSuccess: async (data) => {
      setAuth(data.access_token, { id: 'temp', email: '', full_name: 'Security Operator' });
      try {
        const userRes = await api.get('/auth/me');
        setAuth(data.access_token, userRes.data);
      } catch (err) {
        console.error("Failed to fetch user profile, using fallback:", err);
        setAuth(data.access_token, { id: 'default', email: 'operator@campus.cctv', full_name: 'Security Operator' });
      }
      navigate('/');
    },
    onError: (err: any) => {
      const msg = err.response?.data?.detail || "Authentication failed. Verify credentials.";
      setError("root", { type: "manual", message: msg });
    }
  });

  const onSubmit = (data: any) => {
    mutation.mutate(data);
  };

  return (
    <div className="min-h-screen bg-dark-bg flex items-center justify-center px-4">
      <div className="max-w-md w-full bg-dark-card border border-dark-border rounded-2xl p-8 shadow-2xl space-y-8">
        <div className="text-center space-y-2">
          <h2 className="text-2xl font-bold text-slate-100 tracking-tight">Smart Campus Security</h2>
          <p className="text-slate-400 text-sm">Sign in to operator dashboard credentials</p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
          {errors.root && (
            <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg p-3 text-center">
              {errors.root.message}
            </div>
          )}

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Email Address</label>
            <div className="relative flex items-center">
              <Mail className="absolute left-3 h-5 w-5 text-slate-500" />
              <input
                type="email"
                {...register('email', { required: 'Email address is required' })}
                placeholder="admin@campus.edu"
                className="w-full pl-10 pr-4 py-3 bg-slate-900 border border-dark-border rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition text-sm"
              />
            </div>
            {errors.email && <span className="text-xs text-red-400 font-medium">{String(errors.email.message)}</span>}
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Password</label>
            <div className="relative flex items-center">
              <Lock className="absolute left-3 h-5 w-5 text-slate-500" />
              <input
                type="password"
                {...register('password', { required: 'Password is required' })}
                placeholder="••••••••"
                className="w-full pl-10 pr-4 py-3 bg-slate-900 border border-dark-border rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition text-sm"
              />
            </div>
            {errors.password && <span className="text-xs text-red-400 font-medium">{String(errors.password.message)}</span>}
          </div>

          <button
            type="submit"
            disabled={mutation.isPending}
            className="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-semibold shadow-lg shadow-blue-500/20 transition flex items-center justify-center space-x-2 text-sm"
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>Authenticating...</span>
              </>
            ) : (
              <span>Operator Login</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
};
