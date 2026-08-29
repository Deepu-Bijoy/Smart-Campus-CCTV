import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuthStore } from './store/useAuthStore';
import { Login } from './pages/Login';
import { Dashboard } from './pages/Dashboard';
import { Videos } from './pages/Videos';
import { Cameras } from './pages/Cameras';
import { CameraDetails } from './pages/CameraDetails';
import { Events } from './pages/Events';
import { EventDetails } from './pages/EventDetails';
import { Reports } from './pages/Reports';
import { ReportDetails } from './pages/ReportDetails';
import { UploadFeed } from './pages/Upload';
import { Students } from './pages/Students';
import { StudentDetails } from './pages/StudentDetails';
import { BulkImport } from './pages/BulkImport';
import { Search } from './pages/Search';
import { TimelinePage } from './pages/TimelinePage';
import { Settings } from './pages/Settings';
import { Sidebar } from './components/Sidebar';
import { Navbar } from './components/Navbar';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

interface ProtectedRouteProps {
  children: React.ReactElement;
}

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children }) => {
  const token = useAuthStore(state => state.token);
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
};

const Layout: React.FC = () => {
  return (
    <div className="flex bg-dark-bg min-h-screen text-slate-100 font-sans">
      <Sidebar />
      <div className="flex-1 flex flex-col min-h-screen">
        <Navbar />
        <main className="flex-1 p-8 overflow-y-auto max-w-7xl w-full mx-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/videos" element={<Videos />} />
            <Route path="/cameras" element={<Cameras />} />
            <Route path="/cameras/:id" element={<CameraDetails />} />
            <Route path="/events" element={<Events />} />
            <Route path="/events/:id" element={<EventDetails />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/reports/:id" element={<ReportDetails />} />
            <Route path="/upload" element={<UploadFeed />} />
            <Route path="/students" element={<Students />} />
            <Route path="/students/import" element={<BulkImport />} />
            <Route path="/students/:id" element={<StudentDetails />} />
            <Route path="/search" element={<Search />} />
            <Route path="/timeline/:id" element={<TimelinePage />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
