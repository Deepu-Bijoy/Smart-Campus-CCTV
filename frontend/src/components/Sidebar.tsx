import React from 'react';
import { NavLink } from 'react-router-dom';
import { Home, Video, UploadCloud, Users, Search, Settings, Camera, ShieldAlert, FileText } from 'lucide-react';

export const Sidebar: React.FC = () => {
  const menuItems = [
    { name: 'Dashboard', path: '/', icon: Home },
    { name: 'Surveillance Feeds', path: '/videos', icon: Video },
    { name: 'Camera Management', path: '/cameras', icon: Camera },
    { name: 'Security Alerts', path: '/events', icon: ShieldAlert },
    { name: 'Forensic Reports', path: '/reports', icon: FileText },
    { name: 'Upload Feed', path: '/upload', icon: UploadCloud },
    { name: 'Student Directory', path: '/students', icon: Users },
    { name: 'Bulk Enrollment', path: '/students/import', icon: UploadCloud },
    { name: 'Investigation Search', path: '/search', icon: Search },
    { name: 'Settings', path: '/settings', icon: Settings },
  ];

  return (
    <aside className="w-64 bg-dark-card border-r border-dark-border min-h-screen flex flex-col">
      <div className="h-16 flex items-center justify-center border-b border-dark-border px-6">
        <h1 className="text-blue-500 font-bold text-lg tracking-wide uppercase">Smart Campus CCTV</h1>
      </div>
      <nav className="flex-1 py-6 px-4 space-y-2">
        {menuItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              `flex items-center space-x-3 px-4 py-3 rounded-lg transition ${
                isActive
                  ? 'bg-blue-600 text-white font-medium shadow-md shadow-blue-500/20'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`
            }
          >
            <item.icon className="h-5 w-5" />
            <span>{item.name}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
};
