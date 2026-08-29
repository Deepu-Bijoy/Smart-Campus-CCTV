import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { useAuthStore } from '../store/useAuthStore';
import { Bell, ShieldAlert, CheckCheck, Circle, X } from 'lucide-react';

export const NotificationPanel: React.FC = () => {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState('all');
  const [toasts, setToasts] = useState<any[]>([]);

  const { data: notifications = [] } = useQuery({
    queryKey: ['notifications-list'],
    queryFn: async () => {
      const response = await api.get('/notifications');
      return response.data || [];
    },
    refetchInterval: 10000
  });

  const readMutation = useMutation({
    mutationFn: async (id: string) => {
      await api.put(`/notifications/${id}/read`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    }
  });

  const readAllMutation = useMutation({
    mutationFn: async () => {
      await api.put('/notifications/read-all');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    }
  });

  useEffect(() => {
    const token = useAuthStore.getState().token;
    if (!token) return; // Don't connect WebSocket if not authenticated

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = api.defaults.baseURL 
      ? api.defaults.baseURL.replace('http://', '').replace('https://', '') 
      : '127.0.0.1:8000/api/v1';
    const wsUrl = `${protocol}//${host}/notifications/ws?token=${encodeURIComponent(token)}`;
    
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl);
      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'NOTIFICATION') {
            queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
            setToasts((prev) => [...prev, payload]);
            setTimeout(() => {
              setToasts((prev) => prev.filter((t) => t.id !== payload.id));
            }, 5000);
          }
        } catch (_) { /* ignore malformed messages */ }
      };
    } catch (e) {
      console.error('WebSocket connection failed:', e);
    }

    return () => {
      if (ws) ws.close();
    };
  }, [queryClient]);

  const unreadCount = notifications.filter((n: any) => !n.is_read).length;
  const filteredNotifications = notifications.filter((n: any) => {
    if (filter === 'all') return true;
    return n.severity === filter;
  });

  return (
    <div className="relative z-50">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative bg-slate-900 border border-dark-border/80 hover:bg-slate-800 p-2.5 rounded-xl transition text-slate-400 hover:text-slate-200"
      >
        <Bell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-600 text-white font-bold text-[9px] w-4.5 h-4.5 rounded-full flex items-center justify-center border-2 border-slate-950">
            {unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-3 w-96 bg-dark-card border border-dark-border rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[500px]">
          <div className="px-5 py-4 border-b border-dark-border flex justify-between items-center bg-slate-900/40">
            <h4 className="font-bold text-slate-200 text-sm">Security Alerts Log</h4>
            <div className="flex space-x-2">
              {unreadCount > 0 && (
                <button
                  onClick={() => readAllMutation.mutate()}
                  className="text-xs text-blue-500 hover:text-blue-400 font-semibold flex items-center space-x-1"
                >
                  <CheckCheck className="h-3.5 w-3.5" />
                  <span>Read All</span>
                </button>
              )}
            </div>
          </div>

          <div className="flex px-4 py-2 bg-slate-950 border-b border-dark-border gap-2 text-[10px] font-bold uppercase tracking-wider">
            {['all', 'info', 'warning', 'critical'].map((sev) => (
              <button
                key={sev}
                onClick={() => setFilter(sev)}
                className={`px-2.5 py-1 rounded transition border ${
                  filter === sev
                    ? 'bg-blue-600 border-blue-500 text-white'
                    : 'bg-slate-900 border-dark-border text-slate-400 hover:text-slate-200'
                }`}
              >
                {sev}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-dark-border/40">
            {filteredNotifications.length > 0 ? (
              filteredNotifications.map((noti: any) => (
                <div
                  key={noti.id}
                  className={`p-4 flex items-start space-x-3 hover:bg-slate-900/20 transition ${
                    !noti.is_read ? 'bg-blue-600/5' : ''
                  }`}
                >
                  <div className={`p-1.5 rounded-lg border mt-0.5 ${
                    noti.severity === 'critical'
                      ? 'bg-red-500/10 border-red-500/25 text-red-500'
                      : noti.severity === 'warning'
                      ? 'bg-yellow-500/10 border-yellow-500/25 text-yellow-500'
                      : 'bg-blue-500/10 border-blue-500/25 text-blue-500'
                  }`}>
                    <ShieldAlert className="h-4 w-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-start">
                      <span className="font-semibold text-slate-200 text-xs truncate block">{noti.title}</span>
                      {!noti.is_read && (
                        <button
                          onClick={() => readMutation.mutate(noti.id)}
                          className="text-blue-500 hover:text-blue-400 p-0.5"
                        >
                          <Circle className="h-2.5 w-2.5 fill-blue-500" />
                        </button>
                      )}
                    </div>
                    <p className="text-slate-400 text-[11px] mt-1 leading-normal">{noti.message}</p>
                    <span className="text-[9px] text-slate-500 font-mono block mt-1.5">
                      {new Date(noti.created_at).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-12 text-slate-500 text-xs">
                No alert logs match the current filter.
              </div>
            )}
          </div>
        </div>
      )}

      {toasts.length > 0 && (
        <div className="fixed bottom-6 right-6 z-[999] space-y-3 pointer-events-none">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={`w-80 p-4 rounded-xl shadow-2xl border pointer-events-auto flex items-start space-x-3 bg-slate-950 ${
                toast.severity === 'critical'
                  ? 'border-red-500/30 shadow-red-500/5'
                  : toast.severity === 'warning'
                  ? 'border-yellow-500/30 shadow-yellow-500/5'
                  : 'border-blue-500/30 shadow-blue-500/5'
              }`}
            >
              <div className={`p-1.5 rounded-lg border ${
                toast.severity === 'critical'
                  ? 'bg-red-500/10 border-red-500/20 text-red-500'
                  : toast.severity === 'warning'
                  ? 'bg-yellow-500/10 border-yellow-500/20 text-yellow-500'
                  : 'bg-blue-500/10 border-blue-500/20 text-blue-500'
              }`}>
                <ShieldAlert className="h-4 w-4" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-center">
                  <span className="font-bold text-slate-200 text-xs block">{toast.title}</span>
                  <button
                    onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
                    className="text-slate-500 hover:text-slate-300"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <p className="text-slate-400 text-[11px] mt-1 leading-normal">{toast.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
