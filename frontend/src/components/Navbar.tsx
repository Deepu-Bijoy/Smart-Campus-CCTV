import React from 'react';
import { useAuthStore } from '../store/useAuthStore';
import { LogOut, User, Activity } from 'lucide-react';
import { NotificationPanel } from './NotificationPanel';

export const Navbar: React.FC = () => {
  const { user, logout } = useAuthStore();

  return (
    <header className="h-16 bg-dark-card border-b border-dark-border flex items-center justify-between px-8">
      <div className="flex items-center space-x-2 text-green-500 text-sm font-medium bg-green-500/10 px-3 py-1.5 rounded-full border border-green-500/20">
        <Activity className="h-4 w-4 animate-pulse" />
        <span>System Status: Healthy</span>
      </div>
      <div className="flex items-center space-x-6">
        <NotificationPanel />
        <div className="flex items-center space-x-2 text-slate-300">
          <User className="h-5 w-5 text-slate-400" />
          <span className="text-sm font-medium">{user?.full_name || 'Security Operator'}</span>
        </div>
        <button
          onClick={logout}
          className="flex items-center space-x-2 text-slate-400 hover:text-red-400 transition text-sm font-medium"
        >
          <LogOut className="h-4 w-4" />
          <span>Sign Out</span>
        </button>
      </div>
    </header>
  );
};
