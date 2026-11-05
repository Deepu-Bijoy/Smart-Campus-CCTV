import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { useAuthStore } from '../store/useAuthStore';
import { 
  ArrowLeft, 
  Video, 
  Clock, 
  Users, 
  X, 
  Maximize2, 
  Loader2, 
  Image as ImageIcon,
  Trash2,
  AlertTriangle,
  Play
} from 'lucide-react';
import { AuthenticatedImage } from '../components/AuthenticatedImage';

interface VerifiedStudent {
  id: string;
  name: string;
  rollNumber: string;
  className?: string | null;
  department?: string | null;
  semesterYear?: string | null;
  section?: string | null;
  profilePhotoUrl?: string | null;
}

const formatSemesterYear = (semester?: number | string | null, year?: number | string | null): string => {
  const hasSem = semester !== undefined && semester !== null && semester !== '' && semester !== 0;
  const hasYr = year !== undefined && year !== null && year !== '' && year !== 0;
  if (hasSem && hasYr) {
    return `Semester ${semester} (Year ${year})`;
  }
  if (hasSem) return `Semester ${semester}`;
  if (hasYr) return `Year ${year}`;
  return 'Not available';
};

export const EventDetails: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const [isEnlarged, setIsEnlarged] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showVideoModal, setShowVideoModal] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Fetch security alert details
  const { data: event, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['event-detail', id],
    queryFn: async () => {
      const response = await api.get(`/events/${id}`);
      return response.data;
    },
    staleTime: 30000,
    retry: (failureCount, err: any) => {
      // Prevent repeated automatic retries for a confirmed 404
      if (err?.response?.status === 404) {
        return false;
      }
      // Allow up to 2 retries for transient network failures or server errors
      return failureCount < 2;
    },
    refetchOnWindowFocus: (query) => {
      // Do not refetch on window focus if confirmed 404
      if ((query.state.error as any)?.response?.status === 404) {
        return false;
      }
      return true;
    },
    refetchInterval: false,
  });

  // Fetch video details to resolve filename if video_id is present
  const videoId = event?.video_id;
  const { data: videoData } = useQuery({
    queryKey: ['video-asset', videoId],
    queryFn: async () => {
      if (!videoId) return null;
      try {
        const res = await api.get(`/videos/${videoId}`);
        return res.data;
      } catch {
        return null;
      }
    },
    enabled: Boolean(videoId && !event?.video_name)
  });

  // Handle ESC key for image lightbox and video modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsEnlarged(false);
        setShowVideoModal(false);
      }
    };
    if (isEnlarged || showVideoModal) {
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isEnlarged, showVideoModal]);

  const handleDeleteAlert = async () => {
    if (!id || isDeleting) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await api.delete(`/events/${id}`);
      navigate('/events');
    } catch (err: any) {
      console.error('Failed to delete alert:', err);
      let errMsg = 'Failed to delete alert. Please check your authorization.';
      if (err.response?.status === 403) {
        errMsg = 'Permission denied. Only administrators can delete security alerts.';
      } else if (err.response?.data?.detail) {
        errMsg = err.response.data.detail;
      }
      setDeleteError(errMsg);
      setIsDeleting(false);
    }
  };

  const is404 = (error as any)?.response?.status === 404;

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <div className="flex items-center space-x-2 animate-pulse text-sm">
          <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
          <span>Loading security alert...</span>
        </div>
      </div>
    );
  }

  if (isError || (!event && !isLoading)) {
    return (
      <div className="max-w-5xl mx-auto py-16 px-4 flex flex-col items-center justify-center text-slate-600 h-96 space-y-4">
        <div className="w-12 h-12 rounded-full bg-rose-50 border border-rose-200 flex items-center justify-center text-rose-600 mb-1">
          <AlertTriangle className="h-6 w-6" />
        </div>
        <h2 className="text-lg font-bold text-slate-800">
          {is404 ? 'Security Alert Not Found' : 'Failed to Load Alert Details'}
        </h2>
        <p className="text-xs text-slate-500 max-w-md text-center leading-relaxed">
          {is404
            ? 'The requested security alert event does not exist, has been removed, or the link is invalid.'
            : ((error as any)?.response?.data?.detail || (error as any)?.message || 'A network error occurred while loading alert records.')}
        </p>
        <div className="flex items-center space-x-3 pt-2">
          {!is404 && (
            <button
              onClick={() => refetch()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold transition shadow-xs"
            >
              Retry
            </button>
          )}
          <button
            onClick={() => navigate('/events')}
            className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold transition shadow-xs"
          >
            Back to Alerts
          </button>
        </div>
      </div>
    );
  }

  // --- 1. RESOLVE EVIDENCE SCREENSHOT ---
  const screenshotUrl = event?.evidence_image || null;

  // --- 2. RESOLVE SOURCE VIDEO NAME ---
  const rawVideoName = event?.video_name || videoData?.original_filename || videoData?.title || '';
  const isVideoNameUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(rawVideoName) ||
                          /^[0-9a-f]{32}$/i.test(rawVideoName);
  const videoName = (!rawVideoName || isVideoNameUuid)
    ? 'Campus CCTV Source Footage'
    : rawVideoName;

  // --- 3. RESOLVE VIDEO TIMESTAMP AND INTERVAL ---
  const formatSeconds = (sec: number, preserveMillis = true) => {
    if (isNaN(sec) || sec < 0) return '00:00:00';
    const totalMs = Math.round(sec * 1000);
    const ms = totalMs % 1000;
    const totalSecs = Math.floor(totalMs / 1000);
    const hours = Math.floor(totalSecs / 3600);
    const minutes = Math.floor((totalSecs % 3600) / 60);
    const seconds = totalSecs % 60;
    const base = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    if (preserveMillis && ms > 0) {
      return `${base}.${ms.toString().padStart(3, '0')}`;
    }
    return base;
  };

  const resolveVideoTiming = () => {
    let ts = event?.video_timestamp || null;
    let interval = event?.video_timestamp_interval || null;
    let secVal = typeof event?.video_timestamp_seconds === 'number' ? event.video_timestamp_seconds : null;

    if (!ts || !/^\d{2}:\d{2}:\d{2}/.test(ts)) {
      const expl = event?.explanation || '';
      const rangeMatch = expl.match(/from\s+(\d+(?:\.\d+)?)\s*s\s+to\s+(\d+(?:\.\d+)?)\s*s/i);
      if (rangeMatch) {
        const s1 = parseFloat(rangeMatch[1]);
        const s2 = parseFloat(rangeMatch[2]);
        const mid = (s1 + s2) / 2.0;
        ts = formatSeconds(mid, true);
        interval = `${formatSeconds(s1, false)} - ${formatSeconds(s2, false)}`;
        secVal = mid;
      } else {
        const atMatch = expl.match(/at\s+(\d+(?:\.\d+)?)\s*s/i);
        if (atMatch) {
          const s = parseFloat(atMatch[1]);
          ts = formatSeconds(s, true);
          secVal = s;
        }
      }
    }

    return {
      timestamp: ts || '00:00:00',
      interval,
      seconds: secVal
    };
  };

  const { timestamp: videoTimestamp, interval: videoInterval, seconds: videoSeconds } = resolveVideoTiming();

  // Resolve authenticated video URL for optional seeking navigation
  const rawVideoPath = event?.evidence_video || (videoId ? `/storage/${videoId}.mp4` : null);
  const authenticatedVideoUrl = rawVideoPath
    ? `${rawVideoPath.startsWith('http') ? rawVideoPath : `http://127.0.0.1:8000${rawVideoPath.startsWith('/') ? '' : '/'}${rawVideoPath}`}?token=${encodeURIComponent(token || '')}`
    : null;

  // --- 4. RESOLVE IDENTIFIED STUDENTS (DEDUPLICATED WITH FULL ACADEMIC DETAILS) ---
  const resolveVerifiedStudents = (): VerifiedStudent[] => {
    const map = new Map<string, VerifiedStudent>();

    if (Array.isArray(event?.students)) {
      for (const s of event.students) {
        if (!s || !s.name || s.name.toLowerCase().includes('unknown') || s.name.toLowerCase().includes('unidentified')) continue;
        const key = (s.id || s.student_id || s.roll_number || s.name).toLowerCase();
        if (!map.has(key)) {
          const semYr = formatSemesterYear(s.semester, s.year);
          map.set(key, {
            id: s.id || s.student_id || key,
            name: s.name,
            rollNumber: s.roll_number || 'Not available',
            className: s.class_name || s.class || s.programme || 'Not available',
            department: s.department || 'Not available',
            semesterYear: semYr,
            section: s.section || 'Not available',
            profilePhotoUrl: s.photo_url || s.profile_photo_url || null
          });
        }
      }
    }

    if (event?.student_name && !event.student_name.toLowerCase().includes('unknown') && !event.student_name.toLowerCase().includes('unidentified')) {
      const key = (event.student_id || event.student_roll || event.student_name).toLowerCase();
      if (!map.has(key)) {
        map.set(key, {
          id: event.student_id || key,
          name: event.student_name,
          rollNumber: event.student_roll || 'Not available',
          className: 'Not available',
          department: 'Not available',
          semesterYear: 'Not available',
          section: 'Not available',
          profilePhotoUrl: null
        });
      }
    }

    return Array.from(map.values());
  };
  const verifiedStudents = resolveVerifiedStudents();

  return (
    <div className="max-w-5xl mx-auto py-6 px-4 space-y-6">
      {/* Top Navigation Bar */}
      <div className="flex items-center justify-between border-b border-slate-200 pb-4">
        <button
          onClick={() => navigate('/events')}
          className="inline-flex items-center space-x-2 text-slate-600 hover:text-slate-900 transition text-sm font-semibold cursor-pointer"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Security Alerts</span>
        </button>

        <div className="flex items-center space-x-2.5">
          <button
            onClick={() => {
              setDeleteError(null);
              setShowDeleteModal(true);
            }}
            disabled={isDeleting}
            className="inline-flex items-center space-x-1.5 bg-red-50 hover:bg-red-100 text-red-600 px-3 py-1.5 rounded-lg text-xs font-semibold transition border border-red-200 disabled:opacity-50 cursor-pointer"
            title="Delete this security alert"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span>Delete Alert</span>
          </button>
        </div>
      </div>

      {deleteError && (
        <div className="text-xs text-red-700 bg-red-50 border border-red-200 px-3 py-2 rounded-lg">
          {deleteError}
        </div>
      )}

      {/* Main Alert Card */}
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-slate-200">
          
          {/* 1. EVIDENCE SCREENSHOT */}
          <div className="lg:col-span-7 p-6 flex flex-col justify-center">
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <span className="flex items-center space-x-1.5">
                  <ImageIcon className="h-3.5 w-3.5 text-slate-400" />
                  <span>Evidence Screenshot</span>
                </span>
                {screenshotUrl && (
                  <span className="text-[11px] text-blue-600 font-normal lowercase">Click to enlarge</span>
                )}
              </div>

              {screenshotUrl ? (
                <div 
                  onClick={() => setIsEnlarged(true)}
                  className="group relative rounded-xl overflow-hidden bg-slate-950 border border-slate-200 aspect-video flex items-center justify-center cursor-pointer shadow-inner hover:ring-2 hover:ring-blue-500/50 transition"
                >
                  <AuthenticatedImage
                    src={screenshotUrl}
                    alt="Security Alert Evidence Keyframe"
                    className="w-full h-full object-contain transition group-hover:scale-[1.01]"
                  />
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition flex items-center justify-center opacity-0 group-hover:opacity-100">
                    <span className="inline-flex items-center space-x-1.5 bg-black/75 text-white text-xs px-3 py-1.5 rounded-lg backdrop-blur-sm shadow-md">
                      <Maximize2 className="h-3.5 w-3.5" />
                      <span>Enlarge Image</span>
                    </span>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 aspect-video flex flex-col items-center justify-center text-slate-400 space-y-2">
                  <ImageIcon className="h-8 w-8 text-slate-300" />
                  <span className="text-xs">No evidence screenshot captured</span>
                </div>
              )}
            </div>
          </div>

          {/* 2, 3, 4. VIDEO NAME, TIMESTAMP & IDENTIFIED STUDENTS */}
          <div className="lg:col-span-5 p-6 flex flex-col justify-between space-y-6 bg-slate-50/50">
            
            {/* Top Details: Video Name & Video Timestamp */}
            <div className="space-y-5">
              {/* 2. Video Name */}
              <div className="space-y-1.5">
                <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  <Video className="h-3.5 w-3.5 text-slate-400" />
                  <span>Source Video</span>
                </div>
                <div className="p-3 bg-white border border-slate-200 rounded-xl">
                  <span className="text-sm font-mono font-semibold text-slate-800 break-all select-all block">
                    {videoName}
                  </span>
                </div>
              </div>

              {/* 3. Video Timestamp & Interval */}
              <div className="space-y-1.5">
                <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  <Clock className="h-3.5 w-3.5 text-slate-400" />
                  <span>Video Incident Timing</span>
                </div>
                <div className="p-3.5 bg-white border border-slate-200 rounded-xl space-y-2">
                  <div className="flex items-baseline space-x-2">
                    <span className="text-xs font-medium text-slate-500">Detected at:</span>
                    <span className="text-lg font-mono font-bold text-slate-900 tracking-wider">
                      {videoTimestamp}
                    </span>
                    <span className="text-xs text-slate-400 font-sans">(source video position)</span>
                  </div>

                  {videoInterval && (
                    <div className="flex items-baseline space-x-2 text-xs font-mono pt-1.5 border-t border-slate-100">
                      <span className="font-sans font-medium text-slate-500">Incident interval:</span>
                      <span className="font-bold text-slate-800">{videoInterval}</span>
                    </div>
                  )}

                  {authenticatedVideoUrl && (
                    <div className="pt-2 border-t border-slate-100">
                      <button
                        type="button"
                        onClick={() => setShowVideoModal(true)}
                        className="inline-flex items-center space-x-1.5 bg-blue-50 hover:bg-blue-100 text-blue-700 px-3 py-1.5 rounded-lg text-xs font-semibold transition border border-blue-200 cursor-pointer"
                      >
                        <Play className="h-3 w-3 fill-blue-600 text-blue-600" />
                        <span>Play Video at Incident Position ({videoTimestamp})</span>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* 4. Identified Student Details */}
            <div className="space-y-2 pt-2 border-t border-slate-200">
              <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <Users className="h-3.5 w-3.5 text-slate-400" />
                <span>Identified Students</span>
              </div>

              {verifiedStudents.length > 0 ? (
                <div className="space-y-3">
                  {verifiedStudents.map((st) => (
                    <div 
                      key={st.id}
                      className="p-3.5 bg-white border border-slate-200 rounded-xl shadow-xs space-y-2.5 transition hover:border-slate-300"
                    >
                      <div className="flex items-center space-x-3 pb-2.5 border-b border-slate-100">
                        {st.profilePhotoUrl ? (
                          <AuthenticatedImage
                            src={st.profilePhotoUrl}
                            alt={st.name}
                            className="w-11 h-11 rounded-full object-cover border border-slate-200 bg-slate-100 shrink-0 shadow-xs"
                          />
                        ) : (
                          <div className="w-11 h-11 rounded-full bg-blue-50 border border-blue-200 text-blue-700 flex items-center justify-center font-bold text-base shrink-0 shadow-xs">
                            {st.name.charAt(0).toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="font-bold text-slate-900 text-sm leading-tight truncate">
                            {st.name}
                          </div>
                          <div className="text-xs text-slate-500 font-mono mt-0.5">
                            Roll No.: <span className="font-semibold text-slate-800">{st.rollNumber}</span>
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block text-[11px] font-medium">Class</span>
                          <span className="font-semibold text-slate-800 block truncate">
                            {st.className || 'Not available'}
                          </span>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block text-[11px] font-medium">Department</span>
                          <span className="font-semibold text-slate-800 block truncate">
                            {st.department || 'Not available'}
                          </span>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block text-[11px] font-medium">Semester / Year</span>
                          <span className="font-semibold text-slate-800 block truncate">
                            {st.semesterYear || 'Not available'}
                          </span>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block text-[11px] font-medium">Section</span>
                          <span className="font-semibold text-slate-800 block truncate">
                            {st.section || 'Not available'}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-4 bg-white border border-dashed border-slate-200 rounded-xl text-center">
                  <p className="text-xs text-slate-500 italic">
                    No confirmed student identities
                  </p>
                </div>
              )}
            </div>

          </div>
        </div>
      </div>

      {/* Lightbox Modal (Click to Enlarge) */}
      {isEnlarged && screenshotUrl && (
        <div 
          onClick={() => setIsEnlarged(false)}
          className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4 cursor-zoom-out"
        >
          <div 
            onClick={(e) => e.stopPropagation()}
            className="relative max-w-5xl w-full bg-slate-900 border border-slate-700 rounded-2xl p-3 shadow-2xl space-y-3 cursor-default"
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center space-x-2 text-slate-300 text-xs font-mono truncate">
                <span className="font-semibold text-white">{videoName}</span>
                <span className="text-slate-500">•</span>
                <span>{videoTimestamp}</span>
              </div>
              <button
                type="button"
                onClick={() => setIsEnlarged(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition cursor-pointer"
                title="Close enlargement"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Modal Image */}
            <div className="rounded-xl overflow-hidden bg-black max-h-[80vh] flex items-center justify-center">
              <AuthenticatedImage
                src={screenshotUrl}
                alt="Enlarged Security Alert Evidence Keyframe"
                className="w-full h-full object-contain max-h-[80vh]"
              />
            </div>
          </div>
        </div>
      )}

      {/* Video Modal (Play at Incident Position) */}
      {showVideoModal && authenticatedVideoUrl && (
        <div 
          onClick={() => setShowVideoModal(false)}
          className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4 cursor-pointer"
        >
          <div 
            onClick={(e) => e.stopPropagation()}
            className="relative max-w-4xl w-full bg-slate-900 border border-slate-700 rounded-2xl p-4 shadow-2xl space-y-3 cursor-default"
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center space-x-2 text-slate-300 text-xs font-mono truncate">
                <span className="font-semibold text-white">{videoName}</span>
                <span className="text-slate-500">•</span>
                <span className="text-blue-400 font-semibold">Incident Position: {videoTimestamp}</span>
                {videoInterval && (
                  <>
                    <span className="text-slate-500">•</span>
                    <span className="text-slate-400">Interval: {videoInterval}</span>
                  </>
                )}
              </div>
              <button
                type="button"
                onClick={() => setShowVideoModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition cursor-pointer"
                title="Close video player"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Video Player */}
            <div className="rounded-xl overflow-hidden bg-black aspect-video flex items-center justify-center">
              <video
                ref={videoRef}
                src={authenticatedVideoUrl}
                controls
                autoPlay
                onLoadedMetadata={() => {
                  if (videoRef.current && videoSeconds !== null) {
                    videoRef.current.currentTime = videoSeconds;
                  }
                }}
                className="w-full h-full object-contain"
              />
            </div>

            <div className="flex items-center justify-between text-xs text-slate-400 pt-1">
              <span>Seek automatically initiated at incident detection offset ({videoTimestamp}).</span>
              <button
                type="button"
                onClick={() => {
                  if (videoRef.current && videoSeconds !== null) {
                    videoRef.current.currentTime = videoSeconds;
                    videoRef.current.play();
                  }
                }}
                className="text-blue-400 hover:text-blue-300 font-medium cursor-pointer"
              >
                Replay from {videoTimestamp}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-slate-200 space-y-4">
            <div className="flex items-center space-x-3 text-red-600">
              <div className="p-2.5 bg-red-50 rounded-xl border border-red-100">
                <AlertTriangle className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-900">Delete Security Alert</h3>
                <p className="text-xs text-slate-500">Confirm permanent alert removal</p>
              </div>
            </div>
            <p className="text-sm text-slate-600 leading-relaxed">
              Are you sure you want to delete this security alert? This will remove the alert record from the security alerts log. The source CCTV video footage, evidence keyframes, and student directory records will remain preserved.
            </p>
            {deleteError && (
              <div className="text-xs text-red-700 bg-red-50 border border-red-200 p-2.5 rounded-lg">
                {deleteError}
              </div>
            )}
            <div className="flex justify-end space-x-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowDeleteModal(false);
                  setDeleteError(null);
                }}
                disabled={isDeleting}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-lg transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteAlert}
                disabled={isDeleting}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-lg transition flex items-center space-x-1.5 disabled:opacity-50 cursor-pointer"
              >
                {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                <span>{isDeleting ? 'Deleting...' : 'Confirm Delete'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default EventDetails;
