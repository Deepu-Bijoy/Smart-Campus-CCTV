import React from 'react';
import { NavLink } from 'react-router-dom';
import { Home, Video, UploadCloud, Users, Search, Camera, ShieldAlert, Swords, UserPlus } from 'lucide-react';
import { useAuthStore } from '../store/useAuthStore';

export const Sidebar: React.FC = () => {
  const user = useAuthStore((state) => state.user);
  const isAdmin = user?.role?.toLowerCase() === 'admin';

  const menuItems = [
    { name: 'Dashboard', path: '/', icon: Home },
    { name: 'Surveillance Feeds', path: '/videos', icon: Video },
    { name: 'Camera Management', path: '/cameras', icon: Camera },
    { name: 'Security Alerts', path: '/events', icon: ShieldAlert },
    { name: 'Violence Detection', path: '/violence', icon: Swords },
    { name: 'Upload Feed', path: '/upload', icon: UploadCloud },
    { name: 'Student Directory', path: '/students', icon: Users },
    { name: 'Investigation Search', path: '/search', icon: Search },
  ];

  return (
    <aside className="w-64 bg-white border-r border-slate-200 min-h-screen flex flex-col">
      <div className="h-16 flex items-center justify-center border-b border-slate-200 px-6">
        <h1 className="text-blue-600 font-bold text-lg tracking-wide uppercase">Smart Campus CCTV</h1>
      </div>
      <nav className="flex-1 py-6 px-4 space-y-1.5">
        {menuItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              `flex items-center space-x-3 px-4 py-3 rounded-lg transition text-sm ${
                isActive
                  ? 'bg-blue-50 text-blue-600 font-semibold'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'
              }`
            }
          >
            <item.icon className="h-5 w-5" />
            <span>{item.name}</span>
          </NavLink>
        ))}

        {isAdmin && (
          <div className="pt-3 mt-3 border-t border-slate-200">
            <div className="px-4 pb-2 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
              User Management
            </div>
            <NavLink
              to="/users/create"
              className={({ isActive }) =>
                `flex items-center space-x-3 px-4 py-3 rounded-lg transition text-sm ${
                  isActive
                    ? 'bg-blue-50 text-blue-600 font-semibold'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'
                }`
              }
            >
              <UserPlus className="h-5 w-5" />
              <span>Add User</span>
            </NavLink>
          </div>
        )}
      </nav>
    </aside>
  );
};
