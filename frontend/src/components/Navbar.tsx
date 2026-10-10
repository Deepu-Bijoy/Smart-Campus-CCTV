import React from 'react';
import { useAuthStore } from '../store/useAuthStore';
import { LogOut, User } from 'lucide-react';
import { NotificationPanel } from './NotificationPanel';

export const Navbar: React.FC = () => {
  const { user, logout } = useAuthStore();

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-8 shadow-sm">
      <div />
      <div className="flex items-center space-x-6">
        <NotificationPanel />
        <div className="flex items-center space-x-2 text-slate-700">
          <User className="h-5 w-5 text-slate-500" />
          <span className="text-sm font-semibold">{user?.full_name || 'Security Operator'}</span>
        </div>
        <button
          onClick={logout}
          className="flex items-center space-x-2 text-slate-500 hover:text-red-600 transition text-sm font-medium"
        >
          <LogOut className="h-4 w-4" />
          <span>Sign Out</span>
        </button>
      </div>
    </header>
  );
};
