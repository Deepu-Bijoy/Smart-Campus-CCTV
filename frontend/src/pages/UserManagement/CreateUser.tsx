import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../store/useAuthStore';
import { api } from '../../services/api';
import {
  UserPlus,
  User,
  Mail,
  Lock,
  Shield,
  Eye,
  EyeOff,
  CheckCircle2,
  AlertCircle,
  ArrowLeft,
  Loader2,
  ShieldAlert
} from 'lucide-react';

interface FormState {
  fullName: string;
  email: string;
  role: 'operator' | 'user';
  password: string;
  confirmPassword: string;
}

interface FormErrors {
  fullName?: string;
  email?: string;
  role?: string;
  password?: string;
  confirmPassword?: string;
}

interface CreatedUserInfo {
  id: string;
  email: string;
  fullName?: string;
  role: string;
  created_at: string;
}

export const CreateUser: React.FC = () => {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const isAdmin = user?.role?.toLowerCase() === 'admin';

  const [form, setForm] = useState<FormState>({
    fullName: '',
    email: '',
    role: 'operator',
    password: '',
    confirmPassword: '',
  });

  const [errors, setErrors] = useState<FormErrors>({});
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [successInfo, setSuccessInfo] = useState<CreatedUserInfo | null>(null);

  // Guard: if non-admin renders, show unauthorized view
  if (!isAdmin) {
    return (
      <div className="max-w-xl mx-auto py-12 px-4">
        <div className="bg-red-950/30 border border-red-800/50 rounded-2xl p-8 text-center space-y-4">
          <div className="mx-auto w-12 h-12 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center text-red-400">
            <ShieldAlert className="h-6 w-6" />
          </div>
          <h2 className="text-xl font-bold text-slate-100">Access Restricted</h2>
          <p className="text-sm text-slate-400">
            You do not have permission to access the User Registration portal. Administrator privileges are required.
          </p>
          <button
            type="button"
            onClick={() => navigate('/')}
            className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold transition"
          >
            Return to Dashboard
          </button>
        </div>
      </div>
    );
  }

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};
    const trimmedName = form.fullName.trim();

    // Full Name
    if (!trimmedName) {
      newErrors.fullName = 'Full Name is required';
    } else if (trimmedName.length > 100) {
      newErrors.fullName = 'Full Name must not exceed 100 characters';
    }

    // Email
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    const trimmedEmail = form.email.trim();
    if (!trimmedEmail) {
      newErrors.email = 'Email address is required';
    } else if (!emailRegex.test(trimmedEmail)) {
      newErrors.email = 'Please provide a valid email address';
    }

    // Role
    if (!form.role || (form.role !== 'operator' && form.role !== 'user')) {
      newErrors.role = 'Role must be either Operator or User';
    }

    // Password
    if (!form.password) {
      newErrors.password = 'Password is required';
    } else if (form.password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters long';
    } else if (form.password.length > 100) {
      newErrors.password = 'Password must not exceed 100 characters';
    }

    // Confirm Password
    if (!form.confirmPassword) {
      newErrors.confirmPassword = 'Confirmation password is required';
    } else if (form.password !== form.confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleInputChange = (field: keyof FormState, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    // Clear field-specific error as user edits
    if (errors[field]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
    }
    if (apiError) {
      setApiError(null);
    }
  };

  const resetForm = () => {
    setForm({
      fullName: '',
      email: '',
      role: 'operator',
      password: '',
      confirmPassword: '',
    });
    setErrors({});
    setShowPassword(false);
    setShowConfirmPassword(false);
    setApiError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setApiError(null);

    if (!validateForm()) {
      return;
    }

    setIsSubmitting(true);

    try {
      // Backend expects UserCreate schema:
      // { email: EmailStr, password: str, full_name?: str, role?: str, is_active?: bool }
      const payload = {
        email: form.email.trim().toLowerCase(),
        password: form.password,
        full_name: form.fullName.trim(),
        role: form.role,
        is_active: true,
      };

      const res = await api.post('/auth/signup', payload);

      if (res.status === 201 || res.status === 200) {
        setSuccessInfo({
          id: res.data.id,
          email: res.data.email,
          fullName: res.data.full_name,
          role: res.data.role,
          created_at: res.data.created_at,
        });
        resetForm();
      }
    } catch (err: any) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;

      if (status === 400) {
        setApiError(typeof detail === 'string' ? detail : 'The user with this email already exists in the system.');
      } else if (status === 401) {
        setApiError('Your session has expired. Please log in again.');
      } else if (status === 403) {
        setApiError('You do not have permission to create users.');
      } else if (status === 409) {
        setApiError(typeof detail === 'string' ? detail : 'User conflict detected. Email already in use.');
      } else if (status === 422) {
        if (Array.isArray(detail)) {
          const msgs = detail.map((d: any) => d.msg || `${d.loc?.join('.')}: invalid`).join(', ');
          setApiError(`Validation error: ${msgs}`);
        } else {
          setApiError(typeof detail === 'string' ? detail : 'Validation error occurred.');
        }
      } else if (status >= 500) {
        setApiError('Unable to create user. Please try again.');
      } else {
        setApiError(typeof detail === 'string' ? detail : 'An unexpected error occurred. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto py-4 space-y-6">
      {/* Header and Back navigation */}
      <div className="flex items-center justify-between">
        <div>
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex items-center space-x-1.5 text-xs text-slate-400 hover:text-slate-200 transition mb-2"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>Back to Dashboard</span>
          </button>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight flex items-center space-x-2">
            <UserPlus className="h-6 w-6 text-blue-500" />
            <span>Create New User</span>
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Add a new authorized user to the Smart Campus Surveillance System.
          </p>
        </div>
      </div>

      {/* Success Banner */}
      {successInfo && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-2xl p-6 shadow-lg space-y-3">
          <div className="flex items-start space-x-3">
            <CheckCircle2 className="h-5 w-5 text-emerald-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h3 className="text-emerald-400 font-semibold text-sm">User created successfully.</h3>
              <p className="text-slate-300 text-xs mt-1">
                Account for <span className="font-semibold text-white">{successInfo.fullName || successInfo.email}</span> (
                <span className="font-mono text-emerald-300">{successInfo.email}</span>) with role{' '}
                <span className="font-semibold uppercase tracking-wider text-xs px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                  {successInfo.role}
                </span>{' '}
                is active and ready for login.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setSuccessInfo(null)}
              className="text-xs text-slate-400 hover:text-slate-200 underline"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {apiError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-2xl p-4 flex items-start space-x-3 text-red-400 text-sm">
          <AlertCircle className="h-5 w-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <span className="font-medium">{apiError}</span>
          </div>
        </div>
      )}

      {/* Main Registration Card */}
      <div className="bg-dark-card border border-dark-border rounded-2xl p-8 shadow-xl space-y-6">
        <form onSubmit={handleSubmit} className="space-y-6" noValidate>
          {/* Full Name */}
          <div className="space-y-1.5">
            <label htmlFor="fullName" className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
              <span>Full Name</span>
              <span className="text-[10px] text-slate-500 lowercase">required</span>
            </label>
            <div className="relative flex items-center">
              <User className="absolute left-3.5 h-4 w-4 text-slate-500" />
              <input
                id="fullName"
                type="text"
                value={form.fullName}
                onChange={(e) => handleInputChange('fullName', e.target.value)}
                placeholder="e.g. John Doe"
                maxLength={100}
                disabled={isSubmitting}
                className={`w-full pl-10 pr-4 py-2.5 bg-slate-900 border rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none transition text-sm ${
                  errors.fullName
                    ? 'border-red-500 focus:border-red-400'
                    : 'border-dark-border focus:border-blue-500'
                }`}
              />
            </div>
            {errors.fullName && (
              <p className="text-xs text-red-400 font-medium flex items-center space-x-1 mt-1">
                <span>{errors.fullName}</span>
              </p>
            )}
          </div>

          {/* Email Address */}
          <div className="space-y-1.5">
            <label htmlFor="email" className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
              <span>Email Address</span>
              <span className="text-[10px] text-slate-500 lowercase">required</span>
            </label>
            <div className="relative flex items-center">
              <Mail className="absolute left-3.5 h-4 w-4 text-slate-500" />
              <input
                id="email"
                type="email"
                value={form.email}
                onChange={(e) => handleInputChange('email', e.target.value)}
                placeholder="operator@campus.edu"
                disabled={isSubmitting}
                className={`w-full pl-10 pr-4 py-2.5 bg-slate-900 border rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none transition text-sm ${
                  errors.email
                    ? 'border-red-500 focus:border-red-400'
                    : 'border-dark-border focus:border-blue-500'
                }`}
              />
            </div>
            {errors.email && (
              <p className="text-xs text-red-400 font-medium flex items-center space-x-1 mt-1">
                <span>{errors.email}</span>
              </p>
            )}
          </div>

          {/* Role Dropdown */}
          <div className="space-y-1.5">
            <label htmlFor="role" className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
              <span>Role</span>
              <span className="text-[10px] text-slate-500 lowercase">authorized role only</span>
            </label>
            <div className="relative flex items-center">
              <Shield className="absolute left-3.5 h-4 w-4 text-slate-500 pointer-events-none" />
              <select
                id="role"
                value={form.role}
                onChange={(e) => handleInputChange('role', e.target.value as 'operator' | 'user')}
                disabled={isSubmitting}
                className="w-full pl-10 pr-4 py-2.5 bg-slate-900 border border-dark-border rounded-xl text-slate-200 focus:outline-none focus:border-blue-500 transition text-sm appearance-none cursor-pointer"
              >
                <option value="operator">Operator (CCTV Surveillance & Monitoring)</option>
                <option value="user">User (Standard Campus Staff / Read-Only Access)</option>
              </select>
            </div>
            <p className="text-[11px] text-slate-500">
              Administrator privileges remain controlled and cannot be assigned through standard registration.
            </p>
            {errors.role && (
              <p className="text-xs text-red-400 font-medium flex items-center space-x-1 mt-1">
                <span>{errors.role}</span>
              </p>
            )}
          </div>

          {/* Password Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Password */}
            <div className="space-y-1.5">
              <label htmlFor="password" className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                <span>Password</span>
                <span className="text-[10px] text-slate-500 lowercase">min 8 characters</span>
              </label>
              <div className="relative flex items-center">
                <Lock className="absolute left-3.5 h-4 w-4 text-slate-500" />
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={form.password}
                  onChange={(e) => handleInputChange('password', e.target.value)}
                  placeholder="••••••••"
                  disabled={isSubmitting}
                  className={`w-full pl-10 pr-10 py-2.5 bg-slate-900 border rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none transition text-sm ${
                    errors.password
                      ? 'border-red-500 focus:border-red-400'
                      : 'border-dark-border focus:border-blue-500'
                  }`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 text-slate-500 hover:text-slate-300 focus:outline-none"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              {errors.password && (
                <p className="text-xs text-red-400 font-medium flex items-center space-x-1 mt-1">
                  <span>{errors.password}</span>
                </p>
              )}
            </div>

            {/* Confirm Password */}
            <div className="space-y-1.5">
              <label htmlFor="confirmPassword" className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                <span>Confirm Password</span>
                <span className="text-[10px] text-slate-500 lowercase">match password</span>
              </label>
              <div className="relative flex items-center">
                <Lock className="absolute left-3.5 h-4 w-4 text-slate-500" />
                <input
                  id="confirmPassword"
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={form.confirmPassword}
                  onChange={(e) => handleInputChange('confirmPassword', e.target.value)}
                  placeholder="••••••••"
                  disabled={isSubmitting}
                  className={`w-full pl-10 pr-10 py-2.5 bg-slate-900 border rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none transition text-sm ${
                    errors.confirmPassword
                      ? 'border-red-500 focus:border-red-400'
                      : 'border-dark-border focus:border-blue-500'
                  }`}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-3 text-slate-500 hover:text-slate-300 focus:outline-none"
                  aria-label={showConfirmPassword ? 'Hide confirm password' : 'Show confirm password'}
                >
                  {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              {errors.confirmPassword && (
                <p className="text-xs text-red-400 font-medium flex items-center space-x-1 mt-1">
                  <span>{errors.confirmPassword}</span>
                </p>
              )}
            </div>
          </div>

          {/* Form Actions */}
          <div className="pt-4 border-t border-dark-border/60 flex items-center justify-end space-x-3">
            <button
              type="button"
              onClick={resetForm}
              disabled={isSubmitting}
              className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 rounded-xl text-xs font-semibold transition"
            >
              Reset Form
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-500 text-white rounded-xl font-semibold text-xs shadow-lg shadow-blue-500/20 transition flex items-center space-x-2"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Creating User...</span>
                </>
              ) : (
                <>
                  <UserPlus className="h-4 w-4" />
                  <span>Create User</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
