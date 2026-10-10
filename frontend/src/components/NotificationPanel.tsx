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
    onSuccess: (_, id) => {
      queryClient.setQueryData(['notifications-list'], (old: any[] = []) =>
        old.map((n: any) => (n.id === id ? { ...n, is_read: true } : n))
      );
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    },
    onError: (error) => {
      console.error('Failed to mark notification as read:', error);
    }
  });

  const readAllMutation = useMutation({
    mutationFn: async () => {
      await api.put('/notifications/read-all');
    },
    onSuccess: () => {
      queryClient.setQueryData(['notifications-list'], (old: any[] = []) =>
        old.map((n: any) => ({ ...n, is_read: true }))
      );
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    },
    onError: (error) => {
      console.error('Failed to mark all notifications as read:', error);
    }
  });

  const token = useAuthStore((state) => state.token);

  useEffect(() => {
    if (!token) return;

    let ws: WebSocket | null = null;
    let isMounted = true;
    let reconnectTimeout: any = null;
    let pingInterval: any = null;
    let backoffDelay = 2000;
    const maxBackoff = 30000;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = api.defaults.baseURL 
      ? api.defaults.baseURL.replace('http://', '').replace('https://', '').replace(/\/$/, '') 
      : '127.0.0.1:8000/api/v1';
    const wsUrl = `${protocol}//${host}/notifications/ws?token=${encodeURIComponent(token)}`;

    const connectWebSocket = () => {
      if (!isMounted) return;
      try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          backoffDelay = 2000;
          pingInterval = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              try {
                ws.send(JSON.stringify({ type: 'PING' }));
              } catch (_) {}
            }
          }, 25000);
        };

        ws.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            if (payload.type === 'NOTIFICATION') {
              queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
              setToasts((prev) => {
                const isDuplicate = prev.some(
                  (t) =>
                    t.id === payload.id ||
                    (payload.dedup_key && t.dedup_key === payload.dedup_key) ||
                    (t.title === payload.title && t.message === payload.message)
                );
                if (isDuplicate) {
                  return prev;
                }
                return [...prev, payload];
              });
              setTimeout(() => {
                setToasts((prev) => prev.filter((t) => t.id !== payload.id));
              }, 5000);
            }
          } catch (_) { /* ignore malformed messages */ }
        };

        ws.onclose = (event) => {
          if (pingInterval) {
            clearInterval(pingInterval);
            pingInterval = null;
          }
          if (!isMounted) return;
          if (event.code === 1008) {
            // Policy violation / rate limit: increase backoff
            backoffDelay = Math.min(backoffDelay * 2, maxBackoff);
          }
          reconnectTimeout = setTimeout(() => {
            if (isMounted) connectWebSocket();
          }, backoffDelay);
        };

        ws.onerror = () => {
          // Handled via onclose
        };
      } catch (e) {
        console.error('WebSocket connection failed:', e);
      }
    };

    connectWebSocket();

    return () => {
      isMounted = false;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (pingInterval) clearInterval(pingInterval);
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close();
        }
      }
    };
  }, [token, queryClient]);

  const unreadNotifications = notifications.filter((n: any) => !n.is_read);
  const unreadCount = unreadNotifications.length;

  const filteredNotifications = unreadNotifications.filter((n: any) => {
    if (filter === 'all') return true;
    return n.severity === filter;
  });

  return (
    <div className="relative z-50">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative bg-slate-100 border border-slate-200 hover:bg-slate-200 p-2.5 rounded-xl transition text-slate-600 hover:text-slate-900"
      >
        <Bell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-600 text-white font-bold text-[9px] w-4.5 h-4.5 rounded-full flex items-center justify-center border-2 border-white">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-3 w-96 bg-white border border-slate-200 rounded-2xl shadow-xl overflow-hidden flex flex-col max-h-[500px]">
          <div className="px-5 py-4 border-b border-slate-200 flex justify-between items-center bg-slate-50">
            <div className="flex items-center space-x-2">
              <h4 className="font-bold text-slate-900 text-sm">Security Alerts Log</h4>
              {unreadCount > 0 && (
                <span className="bg-red-100 text-red-700 text-[10px] font-semibold px-2 py-0.5 rounded-full">
                  {unreadCount} unread
                </span>
              )}
            </div>
            <div className="flex space-x-2">
              {unreadCount > 0 && (
                <button
                  onClick={() => readAllMutation.mutate()}
                  disabled={readAllMutation.isPending}
                  className="text-xs text-blue-600 hover:text-blue-700 font-semibold flex items-center space-x-1 disabled:opacity-50"
                >
                  <CheckCheck className="h-3.5 w-3.5" />
                  <span>{readAllMutation.isPending ? 'Marking...' : 'Read All'}</span>
                </button>
              )}
            </div>
          </div>

          <div className="flex px-4 py-2 bg-slate-50 border-b border-slate-200 gap-2 text-[10px] font-bold uppercase tracking-wider">
            {['all', 'info', 'warning', 'critical'].map((sev) => (
              <button
                key={sev}
                onClick={() => setFilter(sev)}
                className={`px-2.5 py-1 rounded transition border ${
                  filter === sev
                    ? 'bg-blue-600 border-blue-600 text-white'
                    : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-100'
                }`}
              >
                {sev}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
            {filteredNotifications.length > 0 ? (
              filteredNotifications.map((noti: any) => (
                <div
                  key={noti.id}
                  className="p-4 flex items-start space-x-3 hover:bg-slate-50 transition bg-blue-50/40"
                >
                  <div className={`p-1.5 rounded-lg border mt-0.5 ${
                    noti.severity === 'critical'
                      ? 'bg-red-50 border-red-200 text-red-600'
                      : noti.severity === 'warning'
                      ? 'bg-amber-50 border-amber-200 text-amber-600'
                      : 'bg-blue-50 border-blue-200 text-blue-600'
                  }`}>
                    <ShieldAlert className="h-4 w-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-start">
                      <span className="font-semibold text-slate-900 text-xs truncate block">{noti.title}</span>
                      <button
                        onClick={() => readMutation.mutate(noti.id)}
                        disabled={readMutation.isPending}
                        className="text-blue-600 hover:text-blue-700 p-0.5"
                        title="Mark as read"
                      >
                        <Circle className="h-2.5 w-2.5 fill-blue-600" />
                      </button>
                    </div>
                    <p className="text-slate-600 text-[11px] mt-1 leading-normal">{noti.message}</p>
                    <span className="text-[9px] text-slate-400 font-mono block mt-1.5">
                      {new Date(noti.created_at).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-12 text-slate-400 text-xs">
                {unreadCount === 0
                  ? 'No unread security alerts.'
                  : 'No unread alert logs match the current filter.'}
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
              className={`w-80 p-4 rounded-xl shadow-2xl border pointer-events-auto flex items-start space-x-3 bg-white ${
                toast.severity === 'critical'
                  ? 'border-red-200 text-slate-900 shadow-red-500/10'
                  : toast.severity === 'warning'
                  ? 'border-amber-200 text-slate-900 shadow-amber-500/10'
                  : 'border-blue-200 text-slate-900 shadow-blue-500/10'
              }`}
            >
              <div className={`p-1.5 rounded-lg border ${
                toast.severity === 'critical'
                  ? 'bg-red-50 border-red-200 text-red-600'
                  : toast.severity === 'warning'
                  ? 'bg-amber-50 border-amber-200 text-amber-600'
                  : 'bg-blue-50 border-blue-200 text-blue-600'
              }`}>
                <ShieldAlert className="h-4 w-4" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-center">
                  <span className="font-bold text-slate-900 text-xs block">{toast.title}</span>
                  <button
                    onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
                    className="text-slate-400 hover:text-slate-600"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <p className="text-slate-600 text-[11px] mt-1 leading-normal">{toast.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
